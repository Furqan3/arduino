from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
import sqlite3
import json
from contextlib import contextmanager

app = FastAPI()

# Allow all origins (all IPs)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database configuration
DATABASE_FILE = "bus_tracking.db"

class GPSData(BaseModel):
    latitude: float
    longitude: float
    timestamp: int
    satellites: Optional[int] = 0

class RFIDData(BaseModel):
    uid: str
    timestamp: int

# Seat management
TOTAL_SEATS = 30

@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row  # This enables column access by name
    try:
        yield conn
    finally:
        conn.close()

def init_database():
    """Initialize the database with required tables"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # GPS history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS gps_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                timestamp INTEGER NOT NULL,
                satellites INTEGER DEFAULT 0,
                datetime TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # RFID scans table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rfid_scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                datetime TEXT NOT NULL,
                action TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # RFID lists table (boarding and alighting)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rfid_lists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT UNIQUE NOT NULL,
                list_type TEXT NOT NULL CHECK (list_type IN ('boarding', 'alighting')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # System settings table (for seat count and other settings)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Insert default seat count if not exists
        cursor.execute('''
            INSERT OR IGNORE INTO system_settings (key, value) VALUES ('current_seat_count', '0')
        ''')
        
        # Insert default RFID lists if empty
        default_boarding = ["F3A02F27", "5E6F7A8B", "9C0D1E2F"]
        default_alighting = ["5331E50C", "E5F6A7B8", "C9D0E1F2"]
        
        for uid in default_boarding:
            cursor.execute('''
                INSERT OR IGNORE INTO rfid_lists (uid, list_type) VALUES (?, 'boarding')
            ''', (uid,))
            
        for uid in default_alighting:
            cursor.execute('''
                INSERT OR IGNORE INTO rfid_lists (uid, list_type) VALUES (?, 'alighting')
            ''', (uid,))
        
        conn.commit()

def get_current_seat_count():
    """Get current seat count from database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM system_settings WHERE key = 'current_seat_count'")
        result = cursor.fetchone()
        return int(result['value']) if result else 0

def update_seat_count(new_count):
    """Update seat count in database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE system_settings 
            SET value = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE key = 'current_seat_count'
        ''', (str(new_count),))
        conn.commit()

def get_rfid_lists():
    """Get boarding and alighting RFID lists from database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get boarding list
        cursor.execute("SELECT uid FROM rfid_lists WHERE list_type = 'boarding'")
        boarding_list = [row['uid'] for row in cursor.fetchall()]
        
        # Get alighting list
        cursor.execute("SELECT uid FROM rfid_lists WHERE list_type = 'alighting'")
        alighting_list = [row['uid'] for row in cursor.fetchall()]
        
        return boarding_list, alighting_list

# Initialize database on startup
init_database()

@app.post("/gps")
async def receive_gps_data(data: GPSData):
    """Receive GPS location data"""
    current_datetime = datetime.now().isoformat()
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO gps_history (latitude, longitude, timestamp, satellites, datetime)
            VALUES (?, ?, ?, ?, ?)
        ''', (data.latitude, data.longitude, data.timestamp, data.satellites, current_datetime))
        
        # Keep only last 100 GPS entries to prevent database bloat
        cursor.execute('''
            DELETE FROM gps_history 
            WHERE id NOT IN (
                SELECT id FROM gps_history 
                ORDER BY created_at DESC 
                LIMIT 100
            )
        ''')
        conn.commit()
    
    print(f"[{datetime.now()}] GPS Location Received:")
    print(f"  Coordinates: {data.latitude}, {data.longitude}")
    print(f"  Satellites: {data.satellites}")
    print(f"  Device Time: {data.timestamp}")
    
    return {
        "status": "success",
        "message": "GPS location received",
        "location": f"{data.latitude}, {data.longitude}"
    }

@app.post("/rfid")
async def receive_rfid_scan(data: RFIDData):
    """Receive RFID card scan data"""
    current_seat_count = get_current_seat_count()
    boarding_list, alighting_list = get_rfid_lists()
    
    action = "none"
    
    # Check if RFID is in boarding or alighting list
    if data.uid in boarding_list:
        if current_seat_count < TOTAL_SEATS:
            current_seat_count += 1
            action = "boarding"
            print(f"  Action: BOARDING - Seats filled: {current_seat_count}/{TOTAL_SEATS}")
        else:
            action = "boarding_denied"
            print(f"  Action: BOARDING DENIED - Bus full!")
    elif data.uid in alighting_list:
        if current_seat_count > 0:
            current_seat_count -= 1
            action = "alighting"
            print(f"  Action: ALIGHTING - Seats filled: {current_seat_count}/{TOTAL_SEATS}")
        else:
            action = "alighting_error"
            print(f"  Action: ALIGHTING ERROR - No passengers!")
    else:
        action = "unknown"
        print(f"  Action: UNKNOWN RFID")
    
    # Update seat count in database
    update_seat_count(current_seat_count)
    
    # Store the scan in database
    current_datetime = datetime.now().isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO rfid_scans (uid, timestamp, datetime, action)
            VALUES (?, ?, ?, ?)
        ''', (data.uid, data.timestamp, current_datetime, action))
        conn.commit()
    
    print(f"[{datetime.now()}] RFID Scan Received:")
    print(f"  UID: {data.uid}")
    print(f"  Device Time: {data.timestamp}")
    
    return {
        "status": "success",
        "message": f"RFID card {data.uid} registered",
        "action": action,
        "current_seats": current_seat_count,
        "total_seats": TOTAL_SEATS
    }

@app.get("/latest/rfid")
async def get_latest_rfid():
    """Get the latest RFID UID scanned"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT uid, timestamp, datetime, action 
            FROM rfid_scans 
            ORDER BY created_at DESC 
            LIMIT 1
        ''')
        result = cursor.fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="No RFID scans available")
        
        return {
            "uid": result['uid'],
            "timestamp": result['timestamp'],
            "datetime": result['datetime'],
            "action": result['action']
        }

@app.get("/latest/location")
async def get_latest_location():
    """Get the latest GPS location"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT latitude, longitude, timestamp, datetime, satellites 
            FROM gps_history 
            ORDER BY created_at DESC 
            LIMIT 1
        ''')
        result = cursor.fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="No GPS data available")
        
        return {
            "latitude": result['latitude'],
            "longitude": result['longitude'],
            "timestamp": result['timestamp'],
            "datetime": result['datetime'],
            "satellites": result['satellites']
        }

@app.get("/seats/count")
async def get_seat_count():
    """Get current seat count and total seats"""
    current_seat_count = get_current_seat_count()
    return {
        "seats_filled": current_seat_count,
        "total_seats": TOTAL_SEATS,
        "seats_available": TOTAL_SEATS - current_seat_count,
        "occupancy_percentage": round((current_seat_count / TOTAL_SEATS) * 100, 2)
    }

@app.get("/rfid/lists")
async def get_rfid_lists_endpoint():
    """Get the boarding and alighting RFID lists"""
    boarding_list, alighting_list = get_rfid_lists()
    return {
        "boarding_list": boarding_list,
        "alighting_list": alighting_list,
        "boarding_count": len(boarding_list),
        "alighting_count": len(alighting_list)
    }

@app.post("/rfid/lists/boarding/add")
async def add_boarding_rfid(uid: str):
    """Add RFID UID to boarding list"""
    uid = uid.upper()
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Check if already exists in boarding list
        cursor.execute("SELECT uid FROM rfid_lists WHERE uid = ? AND list_type = 'boarding'", (uid,))
        if cursor.fetchone():
            return {"status": "exists", "message": f"UID {uid} already in boarding list"}
        
        # Check if exists in alighting list
        cursor.execute("SELECT uid FROM rfid_lists WHERE uid = ? AND list_type = 'alighting'", (uid,))
        if cursor.fetchone():
            return {"status": "error", "message": f"UID {uid} is in alighting list"}
        
        # Add to boarding list
        cursor.execute("INSERT INTO rfid_lists (uid, list_type) VALUES (?, 'boarding')", (uid,))
        conn.commit()
        
        # Get updated count
        cursor.execute("SELECT COUNT(*) as count FROM rfid_lists WHERE list_type = 'boarding'")
        boarding_count = cursor.fetchone()['count']
    
    return {
        "status": "success",
        "message": f"UID {uid} added to boarding list",
        "boarding_count": boarding_count
    }

@app.post("/rfid/lists/alighting/add")
async def add_alighting_rfid(uid: str):
    """Add RFID UID to alighting list"""
    uid = uid.upper()
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Check if already exists in alighting list
        cursor.execute("SELECT uid FROM rfid_lists WHERE uid = ? AND list_type = 'alighting'", (uid,))
        if cursor.fetchone():
            return {"status": "exists", "message": f"UID {uid} already in alighting list"}
        
        # Check if exists in boarding list
        cursor.execute("SELECT uid FROM rfid_lists WHERE uid = ? AND list_type = 'boarding'", (uid,))
        if cursor.fetchone():
            return {"status": "error", "message": f"UID {uid} is in boarding list"}
        
        # Add to alighting list
        cursor.execute("INSERT INTO rfid_lists (uid, list_type) VALUES (?, 'alighting')", (uid,))
        conn.commit()
        
        # Get updated count
        cursor.execute("SELECT COUNT(*) as count FROM rfid_lists WHERE list_type = 'alighting'")
        alighting_count = cursor.fetchone()['count']
    
    return {
        "status": "success",
        "message": f"UID {uid} added to alighting list",
        "alighting_count": alighting_count
    }

@app.delete("/rfid/lists/boarding/{uid}")
async def remove_boarding_rfid(uid: str):
    """Remove RFID UID from boarding list"""
    uid = uid.upper()
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM rfid_lists WHERE uid = ? AND list_type = 'boarding'", (uid,))
        
        if cursor.rowcount > 0:
            conn.commit()
            return {"status": "success", "message": f"UID {uid} removed from boarding list"}
        else:
            return {"status": "not_found", "message": f"UID {uid} not in boarding list"}

@app.delete("/rfid/lists/alighting/{uid}")
async def remove_alighting_rfid(uid: str):
    """Remove RFID UID from alighting list"""
    uid = uid.upper()
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM rfid_lists WHERE uid = ? AND list_type = 'alighting'", (uid,))
        
        if cursor.rowcount > 0:
            conn.commit()
            return {"status": "success", "message": f"UID {uid} removed from alighting list"}
        else:
            return {"status": "not_found", "message": f"UID {uid} not in alighting list"}

@app.post("/seats/reset")
async def reset_seat_count():
    """Reset seat count to zero"""
    update_seat_count(0)
    return {
        "status": "success",
        "message": "Seat count reset",
        "seats_filled": 0,
        "total_seats": TOTAL_SEATS
    }

@app.get("/gps/history")
async def get_gps_history(limit: int = 20):
    """Get recent GPS location history"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get total count
        cursor.execute("SELECT COUNT(*) as total FROM gps_history")
        total_entries = cursor.fetchone()['total']
        
        # Get recent locations
        cursor.execute('''
            SELECT latitude, longitude, timestamp, datetime, satellites 
            FROM gps_history 
            ORDER BY created_at DESC 
            LIMIT ?
        ''', (limit,))
        
        recent_locations = []
        for row in cursor.fetchall():
            recent_locations.append({
                "latitude": row['latitude'],
                "longitude": row['longitude'],
                "timestamp": row['timestamp'],
                "datetime": row['datetime'],
                "satellites": row['satellites']
            })
    
    return {
        "total_entries": total_entries,
        "recent_locations": recent_locations
    }

@app.get("/rfid/history")
async def get_rfid_history(limit: int = 20):
    """Get recent RFID scan history"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get total count
        cursor.execute("SELECT COUNT(*) as total FROM rfid_scans")
        total_scans = cursor.fetchone()['total']
        
        # Get recent scans
        cursor.execute('''
            SELECT uid, timestamp, datetime, action 
            FROM rfid_scans 
            ORDER BY created_at DESC 
            LIMIT ?
        ''', (limit,))
        
        recent_scans = []
        for row in cursor.fetchall():
            recent_scans.append({
                "uid": row['uid'],
                "timestamp": row['timestamp'],
                "datetime": row['datetime'],
                "action": row['action']
            })
    
    return {
        "total_scans": total_scans,
        "recent_scans": recent_scans
    }

@app.get("/rfid/card/{uid}")
async def get_card_history(uid: str):
    """Get scan history for a specific card"""
    uid = uid.upper()
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT uid, timestamp, datetime, action 
            FROM rfid_scans 
            WHERE uid = ? 
            ORDER BY created_at DESC
        ''', (uid,))
        
        scans = []
        for row in cursor.fetchall():
            scans.append({
                "uid": row['uid'],
                "timestamp": row['timestamp'],
                "datetime": row['datetime'],
                "action": row['action']
            })
    
    return {
        "uid": uid,
        "scan_count": len(scans),
        "scans": scans
    }

@app.get("/status")
async def get_system_status():
    """Get overall system status"""
    current_seat_count = get_current_seat_count()
    boarding_list, alighting_list = get_rfid_lists()
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get latest GPS
        cursor.execute('''
            SELECT latitude, longitude, timestamp, datetime, satellites 
            FROM gps_history 
            ORDER BY created_at DESC 
            LIMIT 1
        ''')
        latest_gps_row = cursor.fetchone()
        latest_gps = None
        if latest_gps_row:
            latest_gps = {
                "latitude": latest_gps_row['latitude'],
                "longitude": latest_gps_row['longitude'],
                "timestamp": latest_gps_row['timestamp'],
                "datetime": latest_gps_row['datetime'],
                "satellites": latest_gps_row['satellites']
            }
        
        # Get latest RFID
        cursor.execute('''
            SELECT uid, timestamp, datetime, action 
            FROM rfid_scans 
            ORDER BY created_at DESC 
            LIMIT 1
        ''')
        latest_rfid_row = cursor.fetchone()
        latest_rfid = None
        if latest_rfid_row:
            latest_rfid = {
                "uid": latest_rfid_row['uid'],
                "timestamp": latest_rfid_row['timestamp'],
                "datetime": latest_rfid_row['datetime'],
                "action": latest_rfid_row['action']
            }
        
        # Get counts
        cursor.execute("SELECT COUNT(*) as total FROM gps_history")
        gps_total = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as total FROM rfid_scans")
        rfid_total = cursor.fetchone()['total']
    
    return {
        "system": "online",
        "database": "sqlite",
        "seats": {
            "filled": current_seat_count,
            "total": TOTAL_SEATS,
            "available": TOTAL_SEATS - current_seat_count,
            "occupancy_percentage": round((current_seat_count / TOTAL_SEATS) * 100, 2)
        },
        "gps": {
            "total_entries": gps_total,
            "latest": latest_gps
        },
        "rfid": {
            "total_scans": rfid_total,
            "latest": latest_rfid,
            "boarding_list_count": len(boarding_list),
            "alighting_list_count": len(alighting_list)
        }
    }

@app.get("/")
async def root():
    return {
        "message": "GPS & RFID Bus Tracking API with SQLite Database",
        "database": "SQLite persistent storage",
        "endpoints": {
            "Core Functions": {
                "POST /gps": "Submit GPS coordinates (auto-sent every 10s)",
                "POST /rfid": "Submit RFID scan (sent on card scan)"
            },
            "Latest Data": {
                "GET /latest/rfid": "Get latest RFID UID scanned",
                "GET /latest/location": "Get latest GPS location"
            },
            "Seat Management": {
                "GET /seats/count": "Get current seat count (total: 30)",
                "POST /seats/reset": "Reset seat count to zero"
            },
            "RFID Lists": {
                "GET /rfid/lists": "Get boarding and alighting RFID lists",
                "POST /rfid/lists/boarding/add?uid={uid}": "Add UID to boarding list",
                "POST /rfid/lists/alighting/add?uid={uid}": "Add UID to alighting list",
                "DELETE /rfid/lists/boarding/{uid}": "Remove UID from boarding list",
                "DELETE /rfid/lists/alighting/{uid}": "Remove UID from alighting list"
            },
            "History": {
                "GET /gps/history": "Get recent GPS locations",
                "GET /rfid/history": "Get recent RFID scans",
                "GET /rfid/card/{uid}": "Get scans for specific card"
            },
            "GET /status": "Get complete system status"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run('main:app', host='0.0.0.0', port=8000, reload=True)
