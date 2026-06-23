from .types import DetectedResource
from .detectors import ResourceDetector, ResourceDetectorRegistry, detect_resource
from .office_wps_detector import OfficeWpsDetector
from .email_detector import EmailDetector
from .ide_detector import IdeDetector
from .browser_detector import BrowserDetector
from .local_file_detector import LocalFileDetector
from .resource_identity import infer_resource_from_active_window, infer_resource_for_activity, attach_resource_identity
from .resource_policy import validate_resource_kind, validate_resource_subtype, safe_metadata_json
