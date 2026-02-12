"""Tests for environment variable manager."""

import os
from pathlib import Path

import pytest

from src.utils.env_manager import EnvManager


@pytest.fixture
def temp_env_file(tmp_path):
    """Create a temporary .env file for testing."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        """# Test env file
APP_ENV=development
APP_DEBUG=true

# API Settings
FYERS_APP_ID=TEST123
FYERS_SECRET_KEY=secret123

# Database
DB_HOST=localhost
DB_PORT=5432
"""
    )
    return env_file


@pytest.fixture
def env_manager(temp_env_file):
    """Create EnvManager instance with temp file."""
    return EnvManager(env_path=temp_env_file)


def test_read_env(env_manager):
    """Test reading environment variables from file."""
    env_vars = env_manager.read_env()

    assert env_vars["APP_ENV"] == "development"
    assert env_vars["APP_DEBUG"] == "true"
    assert env_vars["FYERS_APP_ID"] == "TEST123"
    assert env_vars["FYERS_SECRET_KEY"] == "secret123"
    assert env_vars["DB_HOST"] == "localhost"
    assert env_vars["DB_PORT"] == "5432"


def test_read_env_nonexistent_file(tmp_path):
    """Test reading from non-existent file returns empty dict."""
    manager = EnvManager(env_path=tmp_path / "nonexistent.env")
    env_vars = manager.read_env()
    assert env_vars == {}


def test_update_env_existing_variable(env_manager, temp_env_file):
    """Test updating existing environment variable."""
    result = env_manager.update_env({"APP_ENV": "production"})

    assert result is True

    # Verify file was updated
    content = temp_env_file.read_text()
    assert "APP_ENV=production" in content

    # Verify backup was created
    backup_path = temp_env_file.with_suffix(".env.backup")
    assert backup_path.exists()

    # Verify process environment was updated
    assert os.environ["APP_ENV"] == "production"


def test_update_env_new_variable(env_manager, temp_env_file):
    """Test adding new environment variable."""
    result = env_manager.update_env({"NEW_VAR": "new_value"})

    assert result is True

    # Verify file was updated
    content = temp_env_file.read_text()
    assert "NEW_VAR=new_value" in content


def test_update_env_multiple_variables(env_manager, temp_env_file):
    """Test updating multiple variables at once."""
    updates = {
        "APP_ENV": "staging",
        "FYERS_APP_ID": "NEW_APP_ID",
        "NEW_SETTING": "test",
    }

    result = env_manager.update_env(updates)
    assert result is True

    # Verify all updates
    env_vars = env_manager.read_env()
    assert env_vars["APP_ENV"] == "staging"
    assert env_vars["FYERS_APP_ID"] == "NEW_APP_ID"
    assert env_vars["NEW_SETTING"] == "test"


def test_update_env_preserves_comments(env_manager, temp_env_file):
    """Test that updates preserve comment lines."""
    env_manager.update_env({"APP_ENV": "production"})

    content = temp_env_file.read_text()
    assert "# Test env file" in content
    assert "# API Settings" in content
    assert "# Database" in content


def test_update_env_with_spaces(env_manager, temp_env_file):
    """Test updating variables with spaces in values."""
    result = env_manager.update_env({"APP_NAME": "My App Name"})

    assert result is True

    # Verify quotes were added
    content = temp_env_file.read_text()
    assert 'APP_NAME="My App Name"' in content


def test_update_env_no_backup(env_manager, temp_env_file):
    """Test updating without creating backup."""
    result = env_manager.update_env({"APP_ENV": "production"}, create_backup=False)

    assert result is True

    # Verify no backup was created
    backup_path = temp_env_file.with_suffix(".env.backup")
    assert not backup_path.exists()


def test_get_variable(env_manager):
    """Test getting single variable."""
    value = env_manager.get_variable("APP_ENV")
    assert value == "development"


def test_get_variable_with_default(env_manager):
    """Test getting variable with default."""
    value = env_manager.get_variable("NONEXISTENT", default="default_value")
    assert value == "default_value"


def test_create_template(tmp_path):
    """Test creating .env from template."""
    # Create template
    example_file = tmp_path / ".env.example"
    example_file.write_text(
        """APP_ENV=development
FYERS_APP_ID=your_app_id_here
"""
    )

    # Create manager
    env_file = tmp_path / ".env"
    manager = EnvManager(env_path=env_file)

    # Create from template
    result = manager.create_template()
    assert result is True
    assert env_file.exists()

    # Verify content matches
    assert env_file.read_text() == example_file.read_text()


def test_create_template_no_example(tmp_path):
    """Test creating template when .env.example doesn't exist."""
    env_file = tmp_path / ".env"
    manager = EnvManager(env_path=env_file)

    result = manager.create_template()
    assert result is False


def test_create_template_existing_file(tmp_path):
    """Test that create_template doesn't overwrite existing .env."""
    # Create both files
    example_file = tmp_path / ".env.example"
    example_file.write_text("EXAMPLE=1")

    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING=1")

    manager = EnvManager(env_path=env_file)

    result = manager.create_template()
    assert result is False
    assert env_file.read_text() == "EXISTING=1"  # Not overwritten


def test_update_env_empty_value(env_manager, temp_env_file):
    """Test updating with empty value."""
    result = env_manager.update_env({"EMPTY_VAR": ""})

    assert result is True
    content = temp_env_file.read_text()
    assert 'EMPTY_VAR=""' in content


def test_read_env_with_quotes(tmp_path):
    """Test reading values with quotes."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        """SINGLE_QUOTED='value1'
DOUBLE_QUOTED="value2"
NO_QUOTES=value3
"""
    )

    manager = EnvManager(env_path=env_file)
    env_vars = manager.read_env()

    assert env_vars["SINGLE_QUOTED"] == "value1"
    assert env_vars["DOUBLE_QUOTED"] == "value2"
    assert env_vars["NO_QUOTES"] == "value3"
