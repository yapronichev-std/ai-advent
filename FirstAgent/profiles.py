import shutil
from pathlib import Path

USERS_DIR = Path("memory") / "users"


class UserProfileManager:
    def list_users(self) -> list[str]:
        if not USERS_DIR.exists():
            return []
        return sorted(p.name for p in USERS_DIR.iterdir() if p.is_dir())

    def user_exists(self, user_id: str) -> bool:
        return (USERS_DIR / user_id).is_dir()

    def delete_user(self, user_id: str) -> bool:
        path = USERS_DIR / user_id
        if path.exists():
            shutil.rmtree(path)
            return True
        return False

    def get_profile(self, user_id: str) -> list[dict]:
        from memory import MemoryStore
        return MemoryStore(user_id).get_long_term("profile")