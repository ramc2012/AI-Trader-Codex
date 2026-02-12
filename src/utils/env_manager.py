"""Environment variable management utilities.

Provides functions to safely read and write .env files while preserving
comments and formatting.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


class EnvManager:
    """Manages .env file operations."""

    def __init__(self, env_path: Optional[Path] = None):
        """Initialize with path to .env file.

        Args:
            env_path: Path to .env file. Defaults to .env in project root.
        """
        if env_path is None:
            # Get project root (3 levels up from this file)
            project_root = Path(__file__).parent.parent.parent
            env_path = project_root / ".env"

        self.env_path = env_path
        logger.info("env_manager_initialized", path=str(env_path))

    def read_env(self) -> Dict[str, str]:
        """Read all environment variables from .env file.

        Returns:
            Dictionary of environment variable key-value pairs.
        """
        env_vars = {}

        if not self.env_path.exists():
            logger.warning("env_file_not_found", path=str(self.env_path))
            return env_vars

        try:
            with open(self.env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith("#"):
                        continue

                    # Parse KEY=VALUE
                    if "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip()

                        # Remove quotes if present
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]

                        env_vars[key] = value

            logger.info("env_file_read", count=len(env_vars))
            return env_vars

        except Exception as exc:
            logger.error("env_file_read_failed", error=str(exc))
            return {}

    def update_env(self, updates: Dict[str, str], create_backup: bool = True) -> bool:
        """Update environment variables in .env file.

        Preserves comments and formatting. Creates backup before updating.

        Args:
            updates: Dictionary of variables to update.
            create_backup: Whether to create .env.backup before updating.

        Returns:
            True if successful, False otherwise.
        """
        try:
            # Create backup if file exists
            if self.env_path.exists() and create_backup:
                backup_path = self.env_path.with_suffix(".env.backup")
                import shutil

                shutil.copy2(self.env_path, backup_path)
                logger.info("env_backup_created", path=str(backup_path))

            # Read existing file content
            existing_lines = []
            if self.env_path.exists():
                with open(self.env_path, "r") as f:
                    existing_lines = f.readlines()

            # Track which keys were updated
            updated_keys = set()
            new_lines = []

            # Process existing lines
            for line in existing_lines:
                stripped = line.strip()

                # Keep comments and empty lines as-is
                if not stripped or stripped.startswith("#"):
                    new_lines.append(line)
                    continue

                # Check if this line contains a variable we're updating
                if "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in updates:
                        # Update the value
                        new_value = updates[key]
                        # Preserve quotes for values with spaces
                        if " " in new_value or not new_value:
                            new_value = f'"{new_value}"'
                        new_lines.append(f"{key}={new_value}\n")
                        updated_keys.add(key)
                    else:
                        # Keep existing line
                        new_lines.append(line)
                else:
                    new_lines.append(line)

            # Add new variables that weren't in the file
            for key, value in updates.items():
                if key not in updated_keys:
                    if " " in value or not value:
                        value = f'"{value}"'
                    new_lines.append(f"{key}={value}\n")
                    logger.info("env_variable_added", key=key)

            # Write updated content
            with open(self.env_path, "w") as f:
                f.writelines(new_lines)

            logger.info(
                "env_file_updated",
                updated_count=len(updated_keys),
                added_count=len(updates) - len(updated_keys),
            )

            # Update current process environment
            for key, value in updates.items():
                os.environ[key] = value

            return True

        except Exception as exc:
            logger.error("env_file_update_failed", error=str(exc))
            return False

    def get_variable(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a single environment variable.

        Args:
            key: Variable name.
            default: Default value if not found.

        Returns:
            Variable value or default.
        """
        env_vars = self.read_env()
        return env_vars.get(key, default)

    def create_template(self) -> bool:
        """Create .env file from .env.example template.

        Returns:
            True if successful, False otherwise.
        """
        # Handle .env -> .env.example (remove .env, add .example)
        example_path = self.env_path.parent / f"{self.env_path.stem}.example"

        if not example_path.exists():
            logger.error("env_example_not_found", path=str(example_path))
            return False

        if self.env_path.exists():
            logger.warning("env_file_already_exists", path=str(self.env_path))
            return False

        try:
            import shutil

            shutil.copy2(example_path, self.env_path)
            logger.info("env_file_created_from_template")
            return True
        except Exception as exc:
            logger.error("env_template_copy_failed", error=str(exc))
            return False
