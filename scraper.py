"""
Scraper logic for TripAdvisor, Yelp, and Google Maps reviews via Apify.
Adapted from the original colab notebook script — same actors, same
input shapes, just wrapped into reusable functions that return a
DataFrame + the path of the Excel file they wrote.
"""
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
from apify_client import ApifyClient

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _get_client() -> ApifyClient:
    token = os.getenv("APIFY_TOKEN")
    if not token:
        raise RuntimeError(
            "APIFY_TOKEN is not set. Create backend/.env from .env.example "
            "and add your token there."
        )
    return ApifyClient(token)


def _safe_filename(restaurant_name: str, suffix: str) -> str:
    cleaned = "".join(c for c in restaurant_name if c.isalnum() or c in (" ", "_", "-")).strip()
    return os.path.join(OUTPUT_DIR, f"{cleaned}_{suffix}.xlsx")


def _dataset_id(run) -> str:
    """
    Extract the default dataset id from an actor run result.

    apify-client's return shape has changed across major versions:
      - 1.x returns a plain dict: run["defaultDatasetId"]
      - 3.x returns a `Run` object: run.default_dataset_id

    This handles both so the code keeps working regardless of which
    version `pip install` resolves to.
    """
    if hasattr(run, "default_dataset_id"):
        return run.default_dataset_id
    if isinstance(run, dict):
        return run["defaultDatasetId"]
    raise TypeError(f"Unrecognized run result type: {type(run)}")


def scrape_tripadvisor(restaurant_name: str, tripadvisor_url: str) -> dict:
    client = _get_client()

    run_input = {
        "startUrls": [{"url": tripadvisor_url}],
        "maxItemsPerQuery": 100,
        "scrapeReviewerInfo": True,
        "reviewRatings": ["ALL_REVIEW_RATINGS"],
        "reviewsLanguages": ["ALL_REVIEW_LANGUAGES"],
    }

    run = client.actor("maxcopell/tripadvisor-reviews").call(run_input=run_input)
    if run is None:
        raise RuntimeError("TripAdvisor actor run failed")

    data = list(client.dataset(_dataset_id(run)).iterate_items())
    df = pd.DataFrame(data)

    filepath = _safe_filename(restaurant_name, "TripAdvisor")
    df.to_excel(filepath, index=False)

    return {"platform": "tripadvisor", "rows": len(df), "filepath": filepath}


def scrape_yelp(
    restaurant_name: str,
    yelp_url: str,
    date_from: str = "2025-01-01",
    date_to: str | None = None,
) -> dict:
    client = _get_client()

    if date_to is None:
        date_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    run_input = {
        "startUrls": [{"url": yelp_url}],
        "maxReviewsPerUrl": 100,
        "language": "",
        "dateFrom": date_from,
        "dateTo": date_to,
    }

    run = client.actor("tri_angle/yelp-review-scraper").call(run_input=run_input)
    if run is None:
        raise RuntimeError("Yelp actor run failed")

    data = list(client.dataset(_dataset_id(run)).iterate_items())
    df = pd.DataFrame(data)

    filepath = _safe_filename(restaurant_name, "Yelp")
    df.to_excel(filepath, index=False)

    return {"platform": "yelp", "rows": len(df), "filepath": filepath}


def scrape_opentable(
    restaurant_name: str,
    opentable_url: str,
    max_reviews: int = 100,
) -> dict:
    if "/s?" in opentable_url or "opentable.com/s/" in opentable_url:
        raise ValueError(
            "That's an OpenTable search results URL, not a restaurant page. "
            "Open the restaurant from the search results and copy the URL of its own "
            "page instead (it should look like https://www.opentable.com/r/restaurant-name)."
        )

    client = _get_client()

    run_input = {
        "restaurantId": opentable_url,  # accepts a full URL, not just the r/... slug
        "maxResultsPerRestaurant": max_reviews,
    }

    run = client.actor("johnvc/opentable-reviews-api").call(run_input=run_input)
    if run is None:
        raise RuntimeError("OpenTable actor run failed")

    data = list(client.dataset(_dataset_id(run)).iterate_items())

    # Flatten the nested rating/user objects into top-level columns so the
    # sheet matches the flat one-row-per-review shape used by the other platforms.
    rows = []
    for item in data:
        rating = item.get("rating", {}) or {}
        user = item.get("user", {}) or {}
        rows.append({
            "reviewId": item.get("review_id"),
            "restaurantId": item.get("restaurant_id"),
            "reviewerName": user.get("name"),
            "reviewerLocation": user.get("location"),
            "reviewerReviewCount": user.get("number_of_reviews"),
            "dinedAt": item.get("dined_at"),
            "submittedAt": item.get("submitted_at"),
            "review": item.get("content"),
            "overallRating": rating.get("overall"),
            "foodRating": rating.get("food"),
            "serviceRating": rating.get("service"),
            "ambienceRating": rating.get("ambience"),
            "valueRating": rating.get("value"),
            "noiseLevel": rating.get("noise"),
        })

    df = pd.DataFrame(rows)

    filepath = _safe_filename(restaurant_name, "OpenTable")
    df.to_excel(filepath, index=False)

    return {"platform": "open_table", "rows": len(df), "filepath": filepath}


def scrape_google_maps(
    restaurant_name: str,
    place_url: str,
    max_reviews: int = 100,
) -> dict:
    client = _get_client()

    run_input = {
        "startUrls": [{"url": place_url}],
        "maxReviews": max_reviews,
        "language": "en",
        "proxyConfiguration": {
            "useApifyProxy": True,
            "apifyProxyGroups": ["RESIDENTIAL"],
        },
    }

    run = client.actor("compass/google-maps-reviews-scraper").call(run_input=run_input)
    if run is None:
        raise RuntimeError("Google Maps actor run failed")

    data = list(client.dataset(_dataset_id(run)).iterate_items())
    df = pd.DataFrame(data)

    filepath = _safe_filename(restaurant_name, "Google_Review")
    df.to_excel(filepath, index=False)

    return {"platform": "google_maps", "rows": len(df), "filepath": filepath}