import os


APP_BRAND_NAME = os.getenv("APP_BRAND_NAME", "Component Warehouse").strip() or "Component Warehouse"
APP_BACKUP_NAME = os.getenv("APP_BACKUP_NAME", "component-warehouse").strip() or "component-warehouse"
APP_SHOW_BRAND_LOGO = os.getenv("APP_SHOW_BRAND_LOGO", "0") == "1"
APP_SYNC_USER_AGENT = os.getenv("APP_SYNC_USER_AGENT", "ComponentWarehouse-EDA/1.0").strip() or "ComponentWarehouse-EDA/1.0"
