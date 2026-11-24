import os
from datetime import timedelta
from dotenv import load_dotenv

# Load environment variables from .env file before anything else
load_dotenv()


class Config:
    """Base configuration — all shared settings."""

    # Flask secret key for sessions and CSRF protection
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-only-change-this-before-production')

    # ── Session & Cookie Security ─────────────────────────────────────────────
    # Protect cookies from access by client-side scripts (mitigates XSS token theft)
    SESSION_COOKIE_HTTPONLY = True
    # Lax SameSite prevents cross-site request forgery while allowing standard navigation
    SESSION_COOKIE_SAMESITE = 'Lax'
    # Fixed session lifetime to prevent indefinite zombie sessions
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)

    # ── CSRF Protection ───────────────────────────────────────────────────────
    # Configurable via environment; defaults to False in dev unless explicitly enabled
    WTF_CSRF_ENABLED = os.environ.get('WTF_CSRF_ENABLED', 'False').lower() in ('true', '1', 'yes')

    # ── Database ──────────────────────────────────────────────────────────────
    DB_HOST     = os.environ.get('DB_HOST', 'localhost')
    DB_PORT     = os.environ.get('DB_PORT', '3306')
    DB_NAME     = os.environ.get('DB_NAME', 'shelter_system')
    DB_USER     = os.environ.get('DB_USER', 'root')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', '')

    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
    )
    # Disable SQLAlchemy event notification overhead we don't need
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ── Database Connection Pooling & Liveness ────────────────────────────────
    # pool_pre_ping tests connection before using; pool_recycle recycles connections
    # before MySQL wait_timeout drops them (prevents "MySQL server has gone away").
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_recycle': 280,
        'pool_pre_ping': True,
    }

    # ── Application settings (all configurable via .env) ──────────────────────
    # Percentage of max capacity considered safe for planning (e.g. 85 → 85%)
    SAFE_OCCUPANCY_LIMIT_PCT = int(os.environ.get('SAFE_OCCUPANCY_LIMIT_PCT', 85))

    # Configurable occupancy status thresholds (percentage upper bounds)
    #   0 - 60%      -> Safe
    #   61 - 80%     -> Moderate
    #   81 - 95%     -> High
    #   96 - 100%    -> Critical
    #   Above 100%   -> Overcrowded
    OCCUPANCY_THRESHOLD_SAFE     = float(os.environ.get('OCCUPANCY_THRESHOLD_SAFE', 60.0))
    OCCUPANCY_THRESHOLD_MODERATE = float(os.environ.get('OCCUPANCY_THRESHOLD_MODERATE', 80.0))
    OCCUPANCY_THRESHOLD_HIGH     = float(os.environ.get('OCCUPANCY_THRESHOLD_HIGH', 95.0))
    OCCUPANCY_THRESHOLD_CRITICAL = float(os.environ.get('OCCUPANCY_THRESHOLD_CRITICAL', 100.0))

    OCCUPANCY_THRESHOLDS = {
        'safe':        OCCUPANCY_THRESHOLD_SAFE,
        'moderate':    OCCUPANCY_THRESHOLD_MODERATE,
        'high':        OCCUPANCY_THRESHOLD_HIGH,
        'critical':    OCCUPANCY_THRESHOLD_CRITICAL,
    }

    # Scoring weights for the recommendation engine (must sum to 1.0)
    WEIGHT_DISTANCE   = float(os.environ.get('WEIGHT_DISTANCE',   0.25))
    WEIGHT_CAPACITY   = float(os.environ.get('WEIGHT_CAPACITY',   0.35))
    WEIGHT_FACILITIES = float(os.environ.get('WEIGHT_FACILITIES', 0.20))
    WEIGHT_RESOURCES  = float(os.environ.get('WEIGHT_RESOURCES',  0.20))

    # How many hours ahead the prediction engine should forecast
    PREDICT_HOURS_AHEAD = int(os.environ.get('PREDICT_HOURS_AHEAD', 6))


class DevelopmentConfig(Config):
    """Development: debug mode on, verbose errors."""
    DEBUG = True


class ProductionConfig(Config):
    """Production: debug off, strict security enforcement."""
    DEBUG   = False
    TESTING = False
    # Only transmit cookies over HTTPS in production
    SESSION_COOKIE_SECURE = True
    # Strictly enforce CSRF in production
    WTF_CSRF_ENABLED = True


class TestingConfig(Config):
    """Testing: headless execution and automated test runners."""
    TESTING = True
    DEBUG   = False
    # Disable CSRF in tests so test clients can POST without parsing tokens
    WTF_CSRF_ENABLED = False


# Map string names → config classes (used by app.py)
config_by_name = {
    'development': DevelopmentConfig,
    'production':  ProductionConfig,
    'testing':     TestingConfig,
}
