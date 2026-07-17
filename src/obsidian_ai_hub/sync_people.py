from __future__ import annotations

import logging
from obsidian_ai_hub.people_sync.sync import main, sync_people_in_tx

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
