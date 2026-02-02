import asyncio
import aiofiles
import orjson
import datetime
import time
import logging
from string import ascii_uppercase

from typing import Optional

logger_fs_manipulator = logging.getLogger("async_json")

class AsyncJSONStore:
    def __init__(self, data_file: str, file_lock: Optional[asyncio.Lock] = None):
        self.data_file = data_file
        self.file_lock = file_lock or asyncio.Lock()
        self._queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None

    # ---------------- Worker lifecycle ----------------
    async def _worker(self) -> None:
        logger_fs_manipulator.info("async_json worker started.")
        try:
            while True:
                # Ensure cancellation while waiting is handled locally
                try:
                    path, obj = await self._queue.get()
                except asyncio.CancelledError:
                    logger_fs_manipulator.info(
                        "async_json worker cancelled while waiting on queue."
                    )
                    break

                try:
                    data_bytes = orjson.dumps(obj, option=orjson.OPT_INDENT_2)  # type: ignore[attr-defined]
                    async with aiofiles.open(path, mode="wb") as f:
                        await f.write(data_bytes)
                    logger_fs_manipulator.debug(
                        "Wrote JSON to %s (bytes=%d)", path, len(data_bytes)
                    )
                except Exception:
                    logger_fs_manipulator.exception("Failed to write JSON to %s", path)
                finally:
                    # Protect task_done from raising if queue was cancelled concurrently
                    try:
                        self._queue.task_done()
                    except Exception:
                        logger_fs_manipulator.debug(
                            "task_done() failed or queue already emptied on shutdown."
                        )
        finally:
            logger_fs_manipulator.info("async_json worker exiting.")

    @staticmethod
    async def _is_running_test(task) -> bool:
        return task is not None and not task.done()

    async def is_running(self):
        return await self._is_running_test(self._worker_task)

    async def start_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

    async def stop_worker(self, wait: bool = True) -> None:
        if self._worker_task is None:
            return
        if wait:
            await self._queue.join()
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass
        self._worker_task = None
        logger_fs_manipulator.info("async_json worker stopped.")

    # ---------------- Core JSON ops ----------------
    async def save_json(self, path: str, obj: object) -> None:
        """Enqueue a JSON write. Preserves enqueue order."""
        await self._queue.put((path, obj))

    async def read_json(self, path: str) -> Optional[object]:
        """Read JSON file using aiofiles + orjson."""
        try:
            async with aiofiles.open(path, mode="rb") as f:
                data = await f.read()
                if not data:
                    return None
                return orjson.loads(data)
        except FileNotFoundError:
            return None
        except Exception:
            logger_fs_manipulator.exception("Failed to read/parse JSON %s", path)
            return None

    # ---------------- Simplification helpers ----------------
    async def convert_to_simplified(self, data: dict[str, any]) -> dict[str, any]:
        if "user_roles" not in data:
            # Normal simplification
            return await self._simplify_normal(data)

        # --- User roles simplification ---
        user_roles = data.get("user_roles", {})
        unique_roles = list(dict.fromkeys(user_roles.values()))

        if len(unique_roles) > len(ascii_uppercase):
            raise ValueError("Too many unique roles to map to single letters.")

        role_map = {letter: role_id for letter, role_id in zip(ascii_uppercase, unique_roles)}
        reverse_map = {role_id: letter for letter, role_id in role_map.items()}

        simplified_user_roles = {user: reverse_map[role] for user, role in user_roles.items()}

        simplified: dict[str, any] = {}

        # Preserve epoch_last_edited if present
        if "epoch_last_edited" in data:
            simplified["epoch_last_edited"] = data["epoch_last_edited"]

        simplified["role_map"] = role_map
        simplified["simplification_type"] = "user_roles"

        # Copy over any other keys except user_roles, role_map, epoch_last_edited
        for k, v in data.items():
            if k not in ("user_roles", "role_map", "epoch_last_edited"):
                simplified[k] = v

        simplified["user_roles"] = simplified_user_roles
        return simplified

    async def convert_from_simplified(self, simplified_data: dict[str, any]) -> dict[str, any]:
        simplification_type = simplified_data.get("simplification_type")

        if simplification_type == "user_roles" and "role_map" in simplified_data:
            role_map = simplified_data["role_map"]
            user_roles = simplified_data.get("user_roles", {})
            expanded_user_roles = {
                user: role_map[shorthand] for user, shorthand in user_roles.items()
            }

            expanded: dict[str, any] = {"user_roles": expanded_user_roles}

            for k, v in simplified_data.items():
                if k not in ("user_roles", "role_map", "epoch_last_edited", "simplification_type"):
                    expanded[k] = v

            if "epoch_last_edited" in simplified_data:
                expanded["epoch_last_edited"] = simplified_data["epoch_last_edited"]

            return expanded

        elif simplification_type == "normal" and "value_map" in simplified_data:
            value_map = simplified_data["value_map"]
            expanded = {
                k: value_map[v]
                for k, v in simplified_data.items()
                if k not in ("value_map", "simplification_type")
            }
            return expanded

        else:
            # If nothing matches, just return the dict unchanged
            return simplified_data

    async def _simplify_normal(self, data: dict[str, any]) -> dict[str, any]:
        """
        Normal simplification when 'user_roles' is not present.
        Maps unique values to single letters.
        """
        simplified = {}
        unique_values = list(dict.fromkeys(data.values()))

        if len(unique_values) > len(ascii_uppercase):
            raise ValueError("Too many unique values to map to single letters.")

        value_map = {letter: val for letter, val in zip(ascii_uppercase, unique_values)}
        reverse_map = {val: letter for letter, val in value_map.items()}

        for key, val in data.items():
            simplified[key] = reverse_map[val]

        simplified["value_map"] = value_map
        simplified["simplification_type"] = "normal"
        return simplified

    # ---------------- High-level data ops ----------------
    async def load_data(self, filename=None) -> dict[str, any]:
        logger_fs_manipulator.debug(f"Loading data from {filename}...")
        if filename is None:
            filename = self.data_file
        async with self.file_lock:
            logger_fs_manipulator.debug("Acquired file lock for loading.")
            try:
                async with aiofiles.open(filename, "rb") as file:
                    logger_fs_manipulator.debug("Reading file contents...")
                    contents = await file.read()
                    logger_fs_manipulator.debug("File contents read.")
                    if not contents:
                        logger_fs_manipulator.warning(
                            "Data file empty. Creating fresh. Filename: %s", filename
                        )
                        return {"user_roles": {}}
                    logger_fs_manipulator.debug("Parsing JSON contents...")
                    data = orjson.loads(contents)
                    if "role_map" in data:
                        logger_fs_manipulator.debug("Data is simplified. Expanding...")
                        data = await self.convert_from_simplified(data)

                    # logger_fs_manipulator.debug("Data loaded.")
                    logger_fs_manipulator.debug(
                        "Data loaded with %d users. File saved on %s (epoch=%d).",
                        len(data.get("user_roles", {})),
                        datetime.datetime.fromtimestamp(
                            data.get("epoch_last_edited", 0)
                        ).isoformat(),
                        data.get("epoch_last_edited", 0),
                    )

                    return data
            except FileNotFoundError:
                logger_fs_manipulator.info("Data file missing. Creating fresh.")
                return {"user_roles": {}}
            except Exception:
                logger_fs_manipulator.exception("Failed to load data.")
                return {"user_roles": {}}

    async def save_data(self, data: dict[str, any], filename=None) -> bool:
        if filename is None:
            filename = self.data_file
        async with self.file_lock:
            logger_fs_manipulator.debug("Saving data...")
            try:
                logger_fs_manipulator.debug("Simplifing...")
                simplified = await self.convert_to_simplified(data)
                logger_fs_manipulator.debug("Simplified. Inserting epoch...")
                simplified["epoch_last_edited"] = time.time()
                logger_fs_manipulator.debug("Epoch inserted. Writing to file...")
                async with aiofiles.open(filename, "wb") as f:
                    await f.write(orjson.dumps(simplified, option=orjson.OPT_INDENT_2))
                    logger_fs_manipulator.debug("Data written to file.")
            except Exception as e:
                logger_fs_manipulator.error(f"Failed saving data: {e}")
                return False
        try:
            logger_fs_manipulator.debug("Verifying saved data by re-loading...")
            loaded_data = await self.load_data(filename)
            if simplified == loaded_data:
                logger_fs_manipulator.debug(
                    "Verification successful: Data matches after save/load."
                )
            simplified = loaded_data
            logger_fs_manipulator.debug(
                "Data saved with %d users. File saved on %s (epoch=%d).",
                len(simplified.get("user_roles", {})),
                datetime.datetime.fromtimestamp(simplified.get("epoch_last_edited", 0)).isoformat(),
                simplified.get("epoch_last_edited", 0),
            )

            return True
        except Exception as e:
            logger_fs_manipulator.error(f"Failed verifying saved data: {e}")
            return False
