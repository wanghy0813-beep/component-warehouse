import os

from fastapi import HTTPException


FEATURE_EDA_ENABLED = os.getenv("FEATURE_EDA_ENABLED", "0") == "1"


def feature_config() -> dict:
    return {
        "eda": FEATURE_EDA_ENABLED,
    }


def require_eda_enabled() -> None:
    if not FEATURE_EDA_ENABLED:
        raise HTTPException(status_code=404, detail="EDA feature is disabled")
