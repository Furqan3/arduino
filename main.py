from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

app = FastAPI()

# Allow all origins (all IPs)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class GPSData(BaseModel):
    latitude: float
    longitude: float
    timestamp: int
    satellites: Optional[int] = 0

class RFIDData(BaseModel):
    uid: str
    timestamp: int

# Store data in memory (use a database in production)
gps_history = []
rfid_scans = []

# Seat management
TOTAL_SEATS = 30
current_seat_count = 0

# RFID lists for seat management
boarding_rfid_list = [
    "F3A02F27",  
    "5E6F7A8B",
    "9C0D1E2F",
    # Add more UIDs as needed
]

alighting_rfid_list = [
    "5331E50C",  # Example RFID UIDs that decrement seat count
    "E5F6A7B8",
    "C9D0E1F2",
    # Add more UIDs as needed
]

@app.post("/gps")
async def receive_gps_data(data: GPSData):
    """Receive GPS location data"""
    gps_entry = {
        "latitude": data.latitude,
        "longitude": data.longitude,
        "timestamp": data.timestamp,
        "satellites": data.satellites,
        "datetime": datetime.now().isoformat()
    }
    
    # Store GPS data
    gps_history.append(gps_entry)
    
    # Keep only last 100 GPS entries to prevent memory overflow
    if len(gps_history) > 100:
        gps_history.pop(0)
    
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
    global current_seat_count
    
    scan_info = {
        "uid": data.uid,
        "timestamp": data.timestamp,
        "datetime": datetime.now().isoformat(),
        "action": "none"
    }
    
    # Check if RFID is in boarding or alighting list
    if data.uid in boarding_rfid_list:
        if current_seat_count < TOTAL_SEATS:
            current_seat_count += 1
            scan_info["action"] = "boarding"
            print(f"  Action: BOARDING - Seats filled: {current_seat_count}/{TOTAL_SEATS}")
        else:
            scan_info["action"] = "boarding_denied"
            print(f"  Action: BOARDING DENIED - Bus full!")
    elif data.uid in alighting_rfid_list:
        if current_seat_count > 0:
            current_seat_count -= 1
            scan_info["action"] = "alighting"
            print(f"  Action: ALIGHTING - Seats filled: {current_seat_count}/{TOTAL_SEATS}")
        else:
            scan_info["action"] = "alighting_error"
            print(f"  Action: ALIGHTING ERROR - No passengers!")
    else:
        scan_info["action"] = "unknown"
        print(f"  Action: UNKNOWN RFID")
    
    # Store the scan
    rfid_scans.append(scan_info)
    
    print(f"[{datetime.now()}] RFID Scan Received:")
    print(f"  UID: {data.uid}")
    print(f"  Device Time: {data.timestamp}")
    
    return {
        "status": "success",
        "message": f"RFID card {data.uid} registered",
        "action": scan_info["action"],
        "current_seats": current_seat_count,
        "total_seats": TOTAL_SEATS
    }

@app.get("/latest/rfid")
async def get_latest_rfid():
    """Get the latest RFID UID scanned"""
    if not rfid_scans:
        raise HTTPException(status_code=404, detail="No RFID scans available")
    
    latest = rfid_scans[-1]
    return {
        "uid": latest["uid"],
        "timestamp": latest["timestamp"],
        "datetime": latest["datetime"],
        "action": latest["action"]
    }

@app.get("/latest/location")
async def get_latest_location():
    """Get the latest GPS location"""
    if not gps_history:
        raise HTTPException(status_code=404, detail="No GPS data available")
    
    latest = gps_history[-1]
    return {
        "latitude": latest["latitude"],
        "longitude": latest["longitude"],
        "timestamp": latest["timestamp"],
        "datetime": latest["datetime"],
        "satellites": latest["satellites"]
    }

@app.get("/seats/count")
async def get_seat_count():
    """Get current seat count and total seats"""
    return {
        "seats_filled": current_seat_count,
        "total_seats": TOTAL_SEATS,
        "seats_available": TOTAL_SEATS - current_seat_count,
        "occupancy_percentage": round((current_seat_count / TOTAL_SEATS) * 100, 2)
    }

@app.get("/rfid/lists")
async def get_rfid_lists():
    """Get the boarding and alighting RFID lists"""
    return {
        "boarding_list": boarding_rfid_list,
        "alighting_list": alighting_rfid_list,
        "boarding_count": len(boarding_rfid_list),
        "alighting_count": len(alighting_rfid_list)
    }

@app.post("/rfid/lists/boarding/add")
async def add_boarding_rfid(uid: str):
    """Add RFID UID to boarding list"""
    uid = uid.upper()
    if uid in boarding_rfid_list:
        return {"status": "exists", "message": f"UID {uid} already in boarding list"}
    if uid in alighting_rfid_list:
        return {"status": "error", "message": f"UID {uid} is in alighting list"}
    
    boarding_rfid_list.append(uid)
    return {
        "status": "success",
        "message": f"UID {uid} added to boarding list",
        "boarding_count": len(boarding_rfid_list)
    }

@app.post("/rfid/lists/alighting/add")
async def add_alighting_rfid(uid: str):
    """Add RFID UID to alighting list"""
    uid = uid.upper()
    if uid in alighting_rfid_list:
        return {"status": "exists", "message": f"UID {uid} already in alighting list"}
    if uid in boarding_rfid_list:
        return {"status": "error", "message": f"UID {uid} is in boarding list"}
    
    alighting_rfid_list.append(uid)
    return {
        "status": "success",
        "message": f"UID {uid} added to alighting list",
        "alighting_count": len(alighting_rfid_list)
    }

@app.delete("/rfid/lists/boarding/{uid}")
async def remove_boarding_rfid(uid: str):
    """Remove RFID UID from boarding list"""
    uid = uid.upper()
    if uid in boarding_rfid_list:
        boarding_rfid_list.remove(uid)
        return {"status": "success", "message": f"UID {uid} removed from boarding list"}
    return {"status": "not_found", "message": f"UID {uid} not in boarding list"}

@app.delete("/rfid/lists/alighting/{uid}")
async def remove_alighting_rfid(uid: str):
    """Remove RFID UID from alighting list"""
    uid = uid.upper()
    if uid in alighting_rfid_list:
        alighting_rfid_list.remove(uid)
        return {"status": "success", "message": f"UID {uid} removed from alighting list"}
    return {"status": "not_found", "message": f"UID {uid} not in alighting list"}

@app.post("/seats/reset")
async def reset_seat_count():
    """Reset seat count to zero"""
    global current_seat_count
    current_seat_count = 0
    return {
        "status": "success",
        "message": "Seat count reset",
        "seats_filled": current_seat_count,
        "total_seats": TOTAL_SEATS
    }

@app.get("/gps/history")
async def get_gps_history(limit: int = 20):
    """Get recent GPS location history"""
    return {
        "total_entries": len(gps_history),
        "recent_locations": gps_history[-limit:] if gps_history else []
    }

@app.get("/rfid/history")
async def get_rfid_history(limit: int = 20):
    """Get recent RFID scan history"""
    return {
        "total_scans": len(rfid_scans),
        "recent_scans": rfid_scans[-limit:] if rfid_scans else []
    }

@app.get("/rfid/card/{uid}")
async def get_card_history(uid: str):
    """Get scan history for a specific card"""
    card_scans = [scan for scan in rfid_scans if scan["uid"] == uid.upper()]
    return {
        "uid": uid.upper(),
        "scan_count": len(card_scans),
        "scans": card_scans
    }

@app.get("/status")
async def get_system_status():
    """Get overall system status"""
    latest_gps = gps_history[-1] if gps_history else None
    latest_rfid = rfid_scans[-1] if rfid_scans else None
    
    return {
        "system": "online",
        "seats": {
            "filled": current_seat_count,
            "total": TOTAL_SEATS,
            "available": TOTAL_SEATS - current_seat_count,
            "occupancy_percentage": round((current_seat_count / TOTAL_SEATS) * 100, 2)
        },
        "gps": {
            "total_entries": len(gps_history),
            "latest": latest_gps
        },
        "rfid": {
            "total_scans": len(rfid_scans),
            "latest": latest_rfid,
            "boarding_list_count": len(boarding_rfid_list),
            "alighting_list_count": len(alighting_rfid_list)
        }
    }

@app.get("/")
async def root():
    return {
        "message": "GPS & RFID Bus Tracking API",
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