"""
Scraper logic for TripAdvisor, Yelp, Google Maps, and OpenTable reviews via Apify.

IMPORTANT — URL requirements per platform:
  Google Maps  : Must be a /place/ URL (open the restaurant, copy URL from address bar).
                 A coordinate viewport (/@lat,lng,z) or search results URL won't work.
  TripAdvisor  : Must be a /Restaurant_Review- URL.
  Yelp         : Must be a /biz/ URL.
  OpenTable    : Must be a /r/ URL (not a /s? search page).
"""
import os
from datetime import datetime, timezone

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
    if hasattr(run, "default_dataset_id"):
        return run.default_dataset_id
    if isinstance(run, dict):
        return run["defaultDatasetId"]
    raise TypeError(f"Unrecognized run result type: {type(run)}")


def _apply_date_filter(df: pd.DataFrame, date_col: str, date_from: str, date_to: str) -> pd.DataFrame:
    """Filter rows to [date_from, date_to] inclusive. Returns tz-naive datetimes (Excel requirement)."""
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce", utc=True)
    from_dt = pd.Timestamp(date_from, tz="UTC")
    to_dt   = pd.Timestamp(date_to,   tz="UTC") + pd.Timedelta(days=1)
    df = df[(df[date_col] >= from_dt) & (df[date_col] < to_dt)]
    df[date_col] = df[date_col].dt.tz_localize(None)  # strip tz — Excel doesn't support tz-aware datetimes
    return df


# ---------------------------------------------------------------------------
# URL validators — catch wrong URL types before spending Apify credits
# ---------------------------------------------------------------------------

def _validate_google_maps_url(url: str):
    if "/place/" not in url:
        raise ValueError(
            "That's not a restaurant page URL. On Google Maps, click on the specific "
            "restaurant until you see its name, photos, and reviews — then copy the URL "
            "from the address bar. It should contain '/place/' and look like:\n"
            "https://www.google.com/maps/place/Burger+King/@22.57,88.36,17z/..."
        )

def _validate_tripadvisor_url(url: str):
    if "Restaurant_Review" not in url and "/Restaurant_Review" not in url:
        raise ValueError(
            "That doesn't look like a TripAdvisor restaurant page URL. "
            "It should contain 'Restaurant_Review' and look like:\n"
            "https://www.tripadvisor.in/Restaurant_Review-g304558-d123456-..."
        )

def _validate_yelp_url(url: str):
    if "/biz/" not in url:
        raise ValueError(
            "That doesn't look like a Yelp business page URL. "
            "It should contain '/biz/' and look like:\n"
            "https://www.yelp.com/biz/burger-king-kolkata"
        )

def _validate_opentable_url(url: str):
    if "/s?" in url or "/s/" in url:
        raise ValueError(
            "That's an OpenTable search results URL. Open the specific restaurant's page "
            "and copy that URL instead — it should look like:\n"
            "https://www.opentable.com/r/burger-king-kolkata"
        )


# ---------------------------------------------------------------------------
# Scrapers
# ---------------------------------------------------------------------------

def scrape_tripadvisor(
    restaurant_name: str,
    tripadvisor_url: str,
    location: str = "",
    date_from: str = "2021-01-01",
    date_to: str | None = None,
) -> dict:
    _validate_tripadvisor_url(tripadvisor_url)
    client = _get_client()

    if date_to is None:
        date_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")

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

    date_col = next((c for c in ["publishedDate", "date", "reviewDate", "createdAt"] if c in df.columns), None)
    if date_col:
        df = _apply_date_filter(df, date_col, date_from, date_to)

    filepath = _safe_filename(restaurant_name, "TripAdvisor")
    df.to_excel(filepath, index=False)

    return {"platform": "tripadvisor", "rows": len(df), "filepath": filepath}


def scrape_yelp(
    restaurant_name: str,
    yelp_url: str,
    date_from: str = "2021-01-01",
    date_to: str | None = None,
) -> dict:
    _validate_yelp_url(yelp_url)
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
    date_from: str = "2021-01-01",
    date_to: str | None = None,
    max_reviews: int = 100,
) -> dict:
    _validate_opentable_url(opentable_url)
    client = _get_client()

    if date_to is None:
        date_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    run_input = {
        "restaurantId": opentable_url,
        "maxResultsPerRestaurant": max_reviews,
    }

    run = client.actor("johnvc/opentable-reviews-api").call(run_input=run_input)
    if run is None:
        raise RuntimeError("OpenTable actor run failed")

    data = list(client.dataset(_dataset_id(run)).iterate_items())

    rows = []
    for item in data:
        rating = item.get("rating", {}) or {}
        user   = item.get("user",   {}) or {}
        rows.append({
            "reviewId":            item.get("review_id"),
            "restaurantId":        item.get("restaurant_id"),
            "reviewerName":        user.get("name"),
            "reviewerLocation":    user.get("location"),
            "reviewerReviewCount": user.get("number_of_reviews"),
            "dinedAt":             item.get("dined_at"),
            "submittedAt":         item.get("submitted_at"),
            "review":              item.get("content"),
            "overallRating":       rating.get("overall"),
            "foodRating":          rating.get("food"),
            "serviceRating":       rating.get("service"),
            "ambienceRating":      rating.get("ambience"),
            "valueRating":         rating.get("value"),
            "noiseLevel":          rating.get("noise"),
        })

    df = pd.DataFrame(rows)

    date_col = next((c for c in ["submittedAt", "dinedAt"] if c in df.columns), None)
    if date_col:
        df = _apply_date_filter(df, date_col, date_from, date_to)

    filepath = _safe_filename(restaurant_name, "OpenTable")
    df.to_excel(filepath, index=False)

    return {"platform": "open_table", "rows": len(df), "filepath": filepath}


def scrape_google_maps(
    restaurant_name: str,
    place_url: str,
    location: str = "",
    date_from: str = "2021-01-01",
    date_to: str | None = None,
    max_reviews: int = 100,
) -> dict:
    _validate_google_maps_url(place_url)
    client = _get_client()

    if date_to is None:
        date_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")

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

    date_col = next((c for c in ["publishedAtDate", "publishAt", "date", "time"] if c in df.columns), None)
    if date_col:
        df = _apply_date_filter(df, date_col, date_from, date_to)

    filepath = _safe_filename(restaurant_name, "Google_Review")
    df.to_excel(filepath, index=False)

    return {"platform": "google_maps", "rows": len(df), "filepath": filepath}