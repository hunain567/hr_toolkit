"""
Real-time punch receiver for ZKTeco devices in Push (ADMS / iclock) mode.

The device is configured with this server's address under
"Cloud Server Setting" / "ADMS". It then calls:

    GET  /iclock/cdata?SN=<serial>&options=all      handshake, we reply with options
    POST /iclock/cdata?SN=<serial>&table=ATTLOG     new punches, one per line
    POST /iclock/cdata?SN=<serial>&table=OPERLOG    operation / user logs (acknowledged only)
    GET  /iclock/getrequest?SN=<serial>             heartbeat, asks for pending commands
    POST /iclock/devicecmd?SN=<serial>              command results (acknowledged only)

The routes are served through a Frappe page renderer (registered in hooks.py
as page_renderer), so no nginx changes are needed.

Devices are matched on "Serial Number" of a Biometric Device whose
Connection Mode is "Push (ADMS)". An unknown serial number creates a
disabled Biometric Device so it can be reviewed and enabled from the desk.
Punches from unknown or disabled devices are refused with HTTP 503, so the
device keeps them and sends them again once the device is enabled.
"""

import frappe
from frappe.utils import cint, now_datetime
from frappe.website.page_renderers.base_renderer import BaseRenderer
from werkzeug.wrappers import Response

from hr_toolkit.biometric_sync import (
    DEVICE_DOCTYPE,
    LOG_DOCTYPE,
    PUSH_MODE,
    _get_settings,
    import_punches,
    update_device_status,
    update_shift_type_last_sync,
)

ROUTE_PREFIX = "iclock"
HEARTBEAT_SECONDS = 10
ERROR_DELAY_SECONDS = 30


class ZKPushRenderer(BaseRenderer):
	"""Serves /iclock/* for ZKTeco push devices."""

	def can_render(self):
		return self.path == ROUTE_PREFIX or self.path.startswith(ROUTE_PREFIX + "/")

	def render(self):
		endpoint = self.path[len(ROUTE_PREFIX) :].strip("/").lower()
		try:
			body, status = handle_request(endpoint)
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title="Biometric Push Error", message=frappe.get_traceback())
			body, status = "ERROR", 500
		return Response(body, status=status, mimetype="text/plain")


def handle_request(endpoint):
	request = frappe.local.request
	serial = (request.args.get("SN") or "").strip()
	if not serial:
		return "ERROR: SN missing", 400

	device = _get_or_register_device(serial)
	if not device:
		return "ERROR: device not registered", 503

	_mark_heartbeat(device.name)

	if not cint(device.enabled):
		frappe.db.commit()
		return "ERROR: device disabled", 503

	if device.ip_address and _request_ip() and device.ip_address != _request_ip():
		frappe.db.commit()
		return "ERROR: IP address not allowed", 403

	if endpoint == "cdata" and request.method == "GET":
		response = _handshake(device)
	elif endpoint == "cdata" and request.method == "POST":
		response = _receive_data(device)
	elif endpoint == "getrequest":
		response = "OK"
	else:
		# devicecmd, ping, registry and anything else: acknowledge
		response = "OK"

	frappe.db.commit()
	return response, 200


# ---------------------------------------------------------------------------
# Device lookup
# ---------------------------------------------------------------------------


def _get_or_register_device(serial):
	name = frappe.db.get_value(
		DEVICE_DOCTYPE,
		{"serial_number": serial, "connection_mode": PUSH_MODE},
		"name",
	)
	if name:
		return frappe.get_doc(DEVICE_DOCTYPE, name)

	# Register an unknown device as disabled so it shows up on the desk.
	device_name = f"ZK-{serial}"
	if frappe.db.exists(DEVICE_DOCTYPE, device_name):
		return None

	device = frappe.new_doc(DEVICE_DOCTYPE)
	device.device_name = device_name
	device.enabled = 0
	device.connection_mode = PUSH_MODE
	device.serial_number = serial
	device.location = "Auto-registered from push request"
	device.punch_direction = "AUTO"
	device.import_from_date = now_datetime().date()
	device.last_sync_message = (
		f"Auto-registered on {now_datetime():%Y-%m-%d %H:%M} from IP {_request_ip() or '-'}. "
		"Review the settings and enable the device to start receiving punches."
	)
	device.insert(ignore_permissions=True)
	frappe.db.commit()
	return None


def _mark_heartbeat(device_name):
	frappe.db.set_value(
		DEVICE_DOCTYPE,
		device_name,
		{"last_heartbeat": now_datetime(), "last_request_ip": _request_ip()},
		update_modified=False,
	)


def _request_ip():
	return getattr(frappe.local, "request_ip", None) or ""


# ---------------------------------------------------------------------------
# Protocol handlers
# ---------------------------------------------------------------------------


def _handshake(device):
	"""Reply with the options the device should use."""
	attlog_stamp = device.push_attlog_stamp or "None"
	lines = [
		f"GET OPTION FROM: {device.serial_number}",
		f"ATTLOGStamp={attlog_stamp}",
		"OPERLOGStamp=9999",
		"ATTPHOTOStamp=None",
		f"ErrorDelay={ERROR_DELAY_SECONDS}",
		f"Delay={HEARTBEAT_SECONDS}",
		"TransTimes=00:00;14:05",
		"TransInterval=1",
		"TransFlag=TransData AttLog",
		"Realtime=1",
		"Encrypt=None",
	]
	return "\n".join(lines) + "\n"


def _receive_data(device):
	request = frappe.local.request
	table = (request.args.get("table") or "").upper()
	lines = _read_body_lines()

	if table != "ATTLOG":
		# OPERLOG, ATTPHOTO, etc. are not used; acknowledge so the device moves on.
		return f"OK: {len(lines)}"

	raw_punches = []
	for line in lines:
		parsed = _parse_attlog_line(line)
		if parsed:
			raw_punches.append(parsed)

	_import_push_batch(device, raw_punches)

	stamp = (request.args.get("Stamp") or "").strip()
	if stamp:
		frappe.db.set_value(DEVICE_DOCTYPE, device.name, "push_attlog_stamp", stamp, update_modified=False)

	return f"OK: {len(lines)}"


def _read_body_lines():
	request = frappe.local.request
	body = request.get_data(cache=True, as_text=True) or ""
	if not body.strip() and request.form:
		# Some firmware sends a form content type; the body then ends up as form keys.
		body = "\n".join(f"{k}={v}" if v else k for k, v in request.form.items())
	return [line.strip("\r") for line in body.split("\n") if line.strip()]


def _parse_attlog_line(line):
	"""
	ATTLOG line format (tab separated):
	    PIN  YYYY-MM-DD HH:MM:SS  punch_state  verify_type  work_code  ...
	"""
	parts = line.split("\t")
	if len(parts) < 2:
		return None
	user_id = parts[0].strip()
	timestamp = parts[1].strip()
	if not user_id or not timestamp:
		return None
	punch_state = parts[2].strip() if len(parts) > 2 and parts[2].strip().isdigit() else None
	return (timestamp, user_id, punch_state)


def _import_push_batch(device, raw_punches):
	if not raw_punches:
		return

	previous_user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		started_on = now_datetime()
		stats = import_punches(device, raw_punches, use_pointer=False)

		log = frappe._dict(stats)
		log.update(
			{
				"device": device.name,
				"triggered_by": "Push",
				"started_on": started_on,
				"finished_on": now_datetime(),
				"status": "Partial" if (stats["failed"] or stats["unmatched"]) else "Success",
			}
		)

		# Keep the log list small: only batches with problems are logged.
		if log.status != "Success":
			log_doc = frappe.new_doc(LOG_DOCTYPE)
			log_doc.update({k: v for k, v in log.items() if k != "latest_punch"})
			log_doc.insert(ignore_permissions=True)

		update_device_status(device, log, stats.get("latest_punch"))

		if stats["checkins_created"] and cint(_get_settings().update_shift_type_last_sync):
			update_shift_type_last_sync(log.finished_on)
	finally:
		frappe.set_user(previous_user)
