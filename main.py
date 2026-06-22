"""
FastAPI backend for the Review Scraper UI.

Run with:
    uvicorn main:app --reload --port 8000

Make sure backend/.env exists with APIFY_TOKEN set (copy from .env.example).
"""
import os
import traceback

from dotenv import load_dotenv
load_dotenv()  # must happen before scraper.py reads os.getenv at call time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import scraper

app = FastAPI(title="Review Scraper API")

# Allow the Vite dev server to call this API during local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScrapeRequest(BaseModel):
    restaurant_name: str
    location: str = ""
    date_from: str = "2021-01-01"
    date_to: str = ""
    tripadvisor_url: str | None = None
    yelp_url: str | None = None
    google_maps_url: str | None = None
    open_table_url: str | None = None
    platforms: list[str]  # subset of ["tripadvisor", "yelp", "google_maps", "open_table"]


@app.get("/api/health")
def health():
    return {"status": "ok", "token_configured": bool(os.getenv("APIFY_TOKEN"))}


@app.post("/api/scrape")
def scrape(req: ScrapeRequest):
    if not req.platforms:
        raise HTTPException(status_code=400, detail="Select at least one platform.")

    results = []
    errors = []

    for platform in req.platforms:
        try:
            if platform == "tripadvisor":
                if not req.tripadvisor_url:
                    raise ValueError("TripAdvisor URL is required.")
                results.append(scraper.scrape_tripadvisor(
                    req.restaurant_name, req.tripadvisor_url,
                    location=req.location, date_from=req.date_from, date_to=req.date_to,
                ))

            elif platform == "yelp":
                if not req.yelp_url:
                    raise ValueError("Yelp URL is required.")
                results.append(scraper.scrape_yelp(
                    req.restaurant_name, req.yelp_url,
                    date_from=req.date_from, date_to=req.date_to,
                ))

            elif platform == "google_maps":
                if not req.google_maps_url:
                    raise ValueError("Google Maps URL is required.")
                results.append(scraper.scrape_google_maps(
                    req.restaurant_name, req.google_maps_url,
                    location=req.location, date_from=req.date_from, date_to=req.date_to,
                ))

            elif platform == "open_table":
                if not req.open_table_url:
                    raise ValueError("OpenTable URL is required.")
                results.append(scraper.scrape_opentable(
                    req.restaurant_name, req.open_table_url,
                    date_from=req.date_from, date_to=req.date_to,
                ))

            else:
                raise ValueError(f"Unknown platform: {platform}")

        except Exception as e:
            traceback.print_exc()
            errors.append({"platform": platform, "error": str(e)})

    return {"results": results, "errors": errors}


@app.get("/api/download")
def download(filepath: str):
    # Restrict downloads to the outputs directory to avoid path traversal.
    abs_outputs = os.path.abspath(scraper.OUTPUT_DIR)
    abs_target = os.path.abspath(filepath)
    if not abs_target.startswith(abs_outputs):
        raise HTTPException(status_code=400, detail="Invalid file path.")
    if not os.path.exists(abs_target):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(abs_target, filename=os.path.basename(abs_target))