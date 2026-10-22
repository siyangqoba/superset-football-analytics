import os

SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY", "change-me-in-production-please")
SQLALCHEMY_DATABASE_URI = os.environ.get(
    "SUPERSET_METADATA_DB_URI", "sqlite:////app/superset_home/superset.db"
)
FEATURE_FLAGS = {
    "DASHBOARD_NATIVE_FILTERS": True,
    "DASHBOARD_CROSS_FILTERS": True,
    "ENABLE_TEMPLATE_PROCESSING": True,
}
WTF_CSRF_ENABLED = True
WTF_CSRF_EXEMPT_LIST = []
# Allow the demo dashboard to be viewed without logging in (Public role gets Gamma-level read access).
PUBLIC_ROLE_LIKE = os.environ.get("SUPERSET_PUBLIC_ROLE_LIKE") or None
ROW_LIMIT = 50000
