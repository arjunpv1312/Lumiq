# Configuration & Database Implementation

## Overview
Comprehensive configuration management and database persistence system for Lumiq application. All features from the security requirements checklist are now fully integrated.

## ✓ Implementation Complete

### 1. **Configuration Management (config.py)**
**File**: `config.py`

Features:
- **Environment-based configuration** with three profiles:
  - `DevelopmentConfig` - Debug enabled, insecure cookies
  - `ProductionConfig` - Debug disabled, secure cookies
  - `TestingConfig` - In-memory database, CSRF disabled
- **Environment variable loading** from `.env` file via `python-dotenv`
- **Centralized settings** for:
  - Flask application settings
  - Session configuration (timeout, security)
  - CSRF protection settings
  - File upload limits and allowed extensions
  - Rate limiting rules for each endpoint
  - Database connection URI
  - Logging configuration
  - Processing parameters

**Usage**:
```python
from config import get_config
config = get_config()
# Access any setting: config.MAX_FILE_SIZE, config.LOG_LEVEL, etc.
```

### 2. **Database Models (models.py)**
**File**: `models.py`

**JobResult Table**:
- Stores analysis results persistently
- Fields: job_id, filename, status, progress, data (JSON), error, trace
- Timestamps: created_at, updated_at, completed_at
- Methods:
  - `set_data(dict)` - Store data as JSON
  - `get_data()` - Retrieve data from JSON
  - `to_dict()` - Convert to response format

**AuditLog Table**:
- Security and operation event tracking
- Fields: timestamp, event_type, severity, user_ip, job_id, action, details, status_code
- Static method: `log_event()` - Create audit entries

**Functions**:
- `store_result(job_id, data_dict)` - Save/update job results
- `get_result(job_id)` - Retrieve job data
- `cleanup_old_jobs(max_age_hours)` - Delete old records
- `init_db(app)` - Initialize database with Flask app

### 3. **Environment Configuration (.env)**
**File**: `.env.example`

Configure via environment variables:
```
FLASK_ENV=production
FLASK_SECRET_KEY=your_secret_key
DATABASE_URL=sqlite:///./data/lumiq.db
LOG_LEVEL=INFO
MAX_FILE_SIZE=52428800
RATELIMIT_UPLOAD=5 per minute
... (30+ configurable settings)
```

**To use**:
1. Copy `.env.example` to `.env`
2. Update values as needed
3. Application loads automatically on startup

### 4. **Comprehensive Error Handling**
**Updates**: `app.py`

Error handlers for HTTP status codes:
- **400** - Bad request (malformed input)
- **403** - Forbidden (CSRF/permission denied)
- **404** - Not found (missing resource)
- **405** - Method not allowed
- **413** - Payload too large (file size exceeded)
- **429** - Rate limit exceeded
- **500** - Internal server error
- **Generic** - Uncaught exceptions

Features:
- Audit logging for all errors
- Security events tracked with IP address
- Detailed error traces in debug mode
- User-friendly error messages in production

### 5. **Request Logging**
**Updates**: `app.py`

Middleware functions:
- `@app.before_request` - Log incoming requests with:
  - Method (GET, POST, etc.)
  - Path
  - Source IP address
  - Unique request ID
  
- `@app.after_request` - Log responses with:
  - Status code
  - Response time (milliseconds)
  - Request method and path

**Output**: 
```
INFO:app:Request: POST /upload from 192.168.1.100
INFO:app:Response: POST /upload - Status: 302 - Duration: 0.45s
```

### 6. **Input Validation**
**Updates**: `app.py`

Validation functions:
- `validate_file_size(file)` - Check file is within limits
  - Max: 50 MB
  - Min: > 0 bytes
  - Returns: (bool, error_message)

- `validate_input(text, max_length)` - Validate text input
  - Max: 5000 characters (configurable)
  - Non-empty check
  - Type validation
  - Returns: (bool, error_message)

- `validate_job_id(job_id)` - Validate UUID format
  - Returns: bool

Applied to all routes:
- `/upload` - File size and name validation
- `/sample` - File existence check
- `/start_process` - Job ID and file path validation
- `/predict` - Text length and content validation
- `/progress` - Job ID validation
- `/results` - Job ID validation
- All download routes - Job ID and file path validation

### 7. **Database-backed Session Storage**
**Replaces**: In-memory `_results = {}` dictionary

**Benefits**:
- ✓ Data persistence across application restarts
- ✓ Queryable job history
- ✓ Scalability (can migrate to PostgreSQL/MySQL)
- ✓ Audit trail maintained
- ✓ Automatic cleanup of old records

**Data Flow**:
```
Route → store_result(job_id, data)
        ↓
      Database (SQLite)
        ↓
      Persistent storage
        ↓
Route → get_result(job_id) → retrieve from DB
```

**Operations**:
- Create job record in database
- Update progress during processing
- Store final results with timestamps
- Query historical jobs
- Automatic cleanup of old records

### 8. **Audit Logging**
**File**: `models.py`

Events tracked:
- **upload**: File upload events
- **sample**: Sample data loading
- **process**: Job processing lifecycle
- **download**: File downloads (CSV, Excel, PDF)
- **predict**: Sentiment predictions
- **cleanup**: Maintenance operations
- **errors**: All error conditions
- **security**: CSRF, rate limit violations, forbidden access

Each event records:
- Timestamp
- Severity level (info, warning, error, critical)
- User IP address
- Job ID (if applicable)
- Action description
- HTTP status code

### 9. **Logging Configuration**
**Features**:
- Dual output: File + Console
- Configurable log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Format includes: timestamp, logger name, level, function, line number, message
- Log file: `logs/lumiq.log`
- Automatic log rotation support (ready for production)

**Example output**:
```
2026-06-05 10:30:45,123 - app - INFO - [upload:210] - File uploaded: data.csv (job_id: abc123, size: 5242880 bytes) from 192.168.1.100
2026-06-05 10:30:46,456 - app - INFO - [run_job:450] - Job abc123: Starting pipeline
2026-06-05 10:30:55,789 - app - INFO - [run_job:550] - Job abc123: Pipeline completed successfully
```

## File Structure

```
.
├── app.py              # Main Flask application (updated)
├── config.py           # Configuration management (NEW)
├── models.py           # Database models (NEW)
├── .env.example        # Environment configuration template (NEW)
├── requirements.txt    # Dependencies (updated)
├── data/               # Database storage directory (NEW)
├── logs/               # Log files directory (NEW)
└── ... (existing files)
```

## New Dependencies

```
flask-sqlalchemy       # ORM for database operations
python-dotenv          # Load .env file
flask-wtf              # Already installed (CSRF)
flask-limiter          # Already installed (Rate limiting)
```

## Database Schema

### JobResult Table
```sql
CREATE TABLE job_results (
    id INTEGER PRIMARY KEY,
    job_id VARCHAR(36) UNIQUE NOT NULL,
    filename VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL,
    progress INTEGER DEFAULT 0,
    data TEXT,                    -- JSON storage
    error TEXT,
    trace TEXT,                   -- Traceback
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    completed_at DATETIME,
    INDEX(job_id)
)
```

### AuditLog Table
```sql
CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    user_ip VARCHAR(45),
    job_id VARCHAR(36),
    action VARCHAR(255) NOT NULL,
    details TEXT,
    status_code INTEGER,
    INDEX(timestamp),
    INDEX(event_type),
    INDEX(job_id)
)
```

## Configuration Examples

### Development Setup
```bash
# .env file
FLASK_ENV=development
FLASK_DEBUG=True
DATABASE_URL=sqlite:///./data/lumiq.db
LOG_LEVEL=DEBUG
```

### Production Setup
```bash
# .env file
FLASK_ENV=production
FLASK_DEBUG=False
DATABASE_URL=postgresql://user:pass@host/lumiq
LOG_LEVEL=INFO
SESSION_COOKIE_SECURE=True
WTF_CSRF_SSL_STRICT=True
```

### Custom Rate Limits
```bash
RATELIMIT_UPLOAD=3 per minute
RATELIMIT_PREDICT=50 per minute
RATELIMIT_DOWNLOAD=30 per minute
```

## Security Features Summary

✓ CSRF protection (Flask-WTF)
✓ Rate limiting (Flask-Limiter) - all endpoints
✓ File size validation (50MB max)
✓ Filename sanitization (secure_filename)
✓ Security headers (CSP, HSTS, etc.)
✓ Input validation (all user inputs)
✓ Error handling (comprehensive HTTP handlers)
✓ Request logging (all requests/responses)
✓ Audit logging (security events)
✓ Secure session configuration (HttpOnly, SameSite, Secure)
✓ Database persistence (no in-memory data loss)

## Usage Instructions

### Initial Setup
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Create `.env` from template:
   ```bash
   copy .env.example .env
   # Edit .env with your settings
   ```

3. Run application:
   ```bash
   python app.py
   ```

### Running with Custom Config
```bash
# Development mode
set FLASK_ENV=development
python app.py

# Production mode
set FLASK_ENV=production
python app.py
```

### Accessing Logs
```bash
# View real-time logs
tail -f logs/lumiq.log

# View all logs
cat logs/lumiq.log
```

### Database Operations
```python
# Query job history
from models import JobResult
jobs = JobResult.query.all()

# Get specific job
job = JobResult.query.filter_by(job_id='xxx-xxx-xxx').first()

# View audit log
from models import AuditLog
events = AuditLog.query.filter_by(event_type='upload').all()

# Cleanup old jobs
from models import cleanup_old_jobs
cleanup_old_jobs(max_age_hours=2)
```

## Verification Checklist

✓ config.py created and compiles
✓ models.py created and compiles
✓ app.py updated and compiles
✓ requirements.txt updated with new packages
✓ New dependencies installed successfully
✓ data/ directory created
✓ logs/ directory created
✓ .env.example created
✓ All routes updated with validation and logging
✓ Error handlers comprehensive
✓ Audit logging implemented
✓ Database persistence working
✓ Request/response logging implemented

## Next Steps (Optional)

1. **Database Migration**: Switch from SQLite to PostgreSQL for production
2. **Log Rotation**: Implement rotating file handlers for production logs
3. **API Documentation**: Add Swagger/OpenAPI documentation
4. **Performance Monitoring**: Add query performance logging
5. **Backup Strategy**: Implement automated database backups
6. **Testing**: Add comprehensive unit and integration tests

## Troubleshooting

**Missing database file?**
- Database is created automatically on first run
- Check `data/lumiq.db` exists
- Verify write permissions on `data/` directory

**Environment variables not loading?**
- Ensure `.env` file exists in project root
- Verify `python-dotenv` is installed
- Check .env file format (KEY=value, one per line)

**Logging not appearing?**
- Check `logs/lumiq.log` file
- Verify `logs/` directory exists
- Check LOG_LEVEL setting in config

**Database locked error?**
- SQLite has limited concurrent access
- Switch to PostgreSQL for production use
- Close other database connections
