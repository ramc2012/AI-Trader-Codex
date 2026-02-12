# 🚀 Getting Started with Claude Code - First Session Guide

Welcome! This guide will help you start developing the Nifty AI Trader with Claude Code desktop app.

---

## ✅ Pre-Session Checklist

Before opening Claude Code, make sure you have:

- [ ] **Claude Code desktop app** installed
- [ ] **Python 3.11+** installed (`python --version`)
- [ ] **Docker Desktop** installed and running
- [ ] **Fyers API account** created at https://myapi.fyers.in/
- [ ] **Fyers API credentials** (App ID, Secret Key, Redirect URI)
- [ ] **Git** installed
- [ ] **Code editor** ready (VS Code recommended)

---

## 📁 Project Files Overview

You should have these files ready:

```
nifty-ai-trader/
├── PROJECT_BRIEF.md          # High-level project overview
├── CURRENT_SPRINT.md         # Current week tasks (Week 1-2)
├── DEVELOPMENT_PLAN.md       # Complete architecture (you provided this earlier)
├── .claudecontext            # Claude Code guidelines
├── .env.example              # Environment variables template
├── .gitignore                # Git ignore rules
├── README.md                 # Project README
└── FIRST_SESSION.md          # This file!
```

---

## 🎯 Session 1 Goals (2-3 hours)

By the end of this session, you should have:

1. ✅ Complete project structure created
2. ✅ Python virtual environment set up
3. ✅ All dependencies installed
4. ✅ Fyers authentication working
5. ✅ Basic FastAPI app running
6. ✅ Docker containers (TimescaleDB, Redis) running

---

## 🚀 Step-by-Step Guide

### Step 1: Open Project in Claude Code

1. **Launch Claude Code desktop app**

2. **Open the project folder**
   - Click "Open Folder" or press `Cmd/Ctrl + O`
   - Navigate to `nifty-ai-trader/` directory
   - Click "Select Folder"

3. **Wait for indexing**
   - Claude Code will index your project files
   - This takes a few seconds

---

### Step 2: Initial Prompt to Claude Code

Once the folder is open, paste this prompt into Claude Code:

```
Hi! I'm starting development on the Nifty AI Trader project.

Please read these context files first:
1. PROJECT_BRIEF.md - Project overview
2. CURRENT_SPRINT.md - Current sprint tasks
3. .claudecontext - Coding standards

After reading, let's begin Sprint 1, Task 1.1: Project Setup.

Please:
1. Confirm you understand the project structure
2. Ask any clarifying questions about the architecture
3. Then we'll start creating the directory structure

Ready?
```

---

### Step 3: Work Through Task 1.1 (Project Setup)

Claude Code will help you create the complete directory structure. Here's what it should create:

**Expected Directory Structure:**
```
nifty-ai-trader/
├── src/
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   └── routes/
│   ├── data/
│   │   ├── __init__.py
│   │   └── collectors/
│   ├── integrations/
│   │   └── __init__.py
│   ├── database/
│   │   ├── __init__.py
│   │   └── models.py
│   ├── utils/
│   │   └── __init__.py
│   └── config/
│       └── settings.py
├── tests/
│   ├── __init__.py
│   └── fixtures/
├── scripts/
├── docs/
├── docker/
├── config/
├── requirements.txt
├── requirements-dev.txt
└── pyproject.toml
```

**After structure is created, continue with:**

```
Great! Now let's set up the Python environment.

Please create:
1. requirements.txt with core dependencies
2. requirements-dev.txt with development tools
3. pyproject.toml for project metadata

Use the tech stack from PROJECT_BRIEF.md.
```

---

### Step 4: Create Virtual Environment (Manual Step)

**In your terminal (outside Claude Code):**

```bash
# Navigate to project
cd nifty-ai-trader

# Create virtual environment
python -m venv venv

# Activate it
source venv/bin/activate  # Mac/Linux
# OR
venv\Scripts\activate     # Windows

# Verify activation
which python              # Should show path to venv/bin/python
```

**Back in Claude Code:**

```
Virtual environment is activated. Now let's install dependencies.

Please verify that requirements.txt includes all necessary packages,
then I'll install them with: pip install -r requirements.txt
```

---

### Step 5: Environment Configuration

```
Now let's set up environment variables.

I have .env.example. Please help me:
1. Review the required variables
2. Create a checklist of what I need from Fyers
3. Guide me on setting up .env file

I have my Fyers credentials ready.
```

**After Claude Code explains, manually create `.env`:**

```bash
cp .env.example .env
# Edit .env with your actual Fyers credentials
```

---

### Step 6: Docker Setup

```
Let's set up the databases.

Please create docker/docker-compose.yml with:
1. TimescaleDB container
2. Redis container
3. Proper volume mounts
4. Network configuration
5. Health checks

Include setup for both development and production.
```

**After docker-compose.yml is created:**

```bash
# In your terminal
cd docker
docker-compose up -d

# Verify containers are running
docker ps

# Check logs
docker-compose logs -f
```

---

### Step 7: Task 1.2 - Fyers Authentication

```
Excellent! Docker containers are running.

Now let's move to Task 1.2: Fyers API Integration.

Please create src/integrations/fyers_client.py with:

1. FyersClient class that handles:
   - OAuth 2.0 authentication
   - Token management (save/load/refresh)
   - Connection health checks
   - Rate limiting
   - Retry logic with exponential backoff

2. Follow the coding standards from .claudecontext:
   - Type hints on all functions
   - Google-style docstrings
   - Async/await for I/O
   - Comprehensive error handling
   - Structured logging

3. Reference: https://api-docs.fyers.in/

Start with the class structure and authentication methods.
```

---

### Step 8: Testing Fyers Authentication

```
Great! Now let's test the Fyers authentication.

Please create scripts/test_fyers_auth.py that:
1. Loads credentials from .env
2. Creates FyersClient instance
3. Initiates authentication flow
4. Prints the authentication URL
5. Waits for auth code input
6. Exchanges code for token
7. Saves token
8. Fetches user profile to verify

Make it user-friendly with clear prompts.
```

**Run the test script:**

```bash
python scripts/test_fyers_auth.py
```

Follow the prompts, authenticate via browser, and verify it works.

---

### Step 9: Session Wrap-Up

```
Excellent work! Let's document what we accomplished.

Please update CURRENT_SPRINT.md:

Move these tasks to "Completed":
- Task 1.1: Project Setup ✅
- Task 1.2: Fyers Integration ✅

Add to "Notes":
- Directory structure created and organized
- Virtual environment configured
- Docker containers running successfully
- Fyers authentication working
- Token persistence implemented

Also create SESSION_01_SUMMARY.md with:
- What we built today
- What's working
- What needs testing
- Priorities for next session
```

---

## 📝 Session 1 Checklist

By end of session, you should have:

- [x] Complete directory structure
- [x] Virtual environment activated
- [x] All dependencies installed
- [x] .env file configured
- [x] Docker containers running (TimescaleDB + Redis)
- [x] Fyers authentication module complete
- [x] Successfully authenticated with Fyers
- [x] Token saved and validated
- [x] User profile retrieved
- [x] Test script working

---

## 🐛 Troubleshooting

### Issue: Dependencies won't install

```bash
# Upgrade pip first
pip install --upgrade pip

# Try installing one by one
pip install fastapi
pip install fyers-apiv3
# etc.
```

### Issue: Docker containers not starting

```bash
# Check Docker Desktop is running
docker --version

# View container logs
docker-compose logs timescaledb
docker-compose logs redis

# Restart containers
docker-compose down
docker-compose up -d
```

### Issue: Fyers authentication failing

1. Verify credentials in .env
2. Check redirect URI matches Fyers app settings
3. Ensure you're using sandbox/production mode correctly
4. Check Fyers API status page

### Issue: Claude Code not finding files

```
Please run: ls -la

This will help me see the directory structure.
```

---

## 🎯 Next Session Preview

**Session 2 will focus on:**

- Task 1.3: Historical OHLC Data Collection
- Task 1.4: TimescaleDB Schema Setup
- Creating database models
- Implementing data collector
- Testing data pipeline

**Preparation for next session:**

```
Before next session, please:
1. Verify Fyers authentication is working
2. Ensure Docker containers stay running
3. Review database schema in CURRENT_SPRINT.md
4. Read TimescaleDB docs (optional)
```

---

## 💡 Tips for Working with Claude Code

### 1. Be Specific
Instead of: "Fix the error"
Say: "I'm getting KeyError: 'timestamp' in fyers_client.py line 45. The API response looks like this: {...}. Can you fix the key access?"

### 2. Build Incrementally
Don't ask for everything at once. Build piece by piece:
- First: Basic class structure
- Then: Core functionality
- Then: Error handling
- Then: Logging
- Finally: Tests

### 3. Review Before Proceeding
Always review generated code before moving to next task:
```
Thanks for creating the FyersClient class. Let me review it.

[after reviewing]

Looks good! Let's add the token persistence feature now.
```

### 4. Use Context
Reference previous work:
```
Using the FyersClient we just created, let's now build
the OHLC collector that will use it for API calls.
```

### 5. Ask for Explanations
```
Can you explain why you chose to use async context manager
here instead of a regular class method?
```

---

## 📚 Helpful Commands Reference

```bash
# Python
python --version                    # Check Python version
pip list                           # List installed packages
pip install -r requirements.txt    # Install dependencies

# Virtual Environment
source venv/bin/activate           # Activate (Mac/Linux)
venv\Scripts\activate              # Activate (Windows)
deactivate                         # Deactivate

# Docker
docker ps                          # List running containers
docker-compose up -d               # Start containers
docker-compose down                # Stop containers
docker-compose logs -f             # View logs
docker-compose restart             # Restart containers

# Git
git status                         # Check status
git add .                          # Stage all changes
git commit -m "feat: message"      # Commit changes
git log --oneline                  # View commit history

# Testing
pytest                             # Run all tests
pytest -v                          # Verbose output
pytest tests/test_fyers_client.py  # Run specific test

# Run FastAPI
uvicorn src.api.main:app --reload  # Run with hot reload
```

---

## 🎓 Learning Resources

**Fyers API:**
- Main Docs: https://api-docs.fyers.in/
- Python SDK: https://github.com/fyers-api/fyers-api-v3
- WebSocket Guide: https://api-docs.fyers.in/web-socket/introduction

**TimescaleDB:**
- Getting Started: https://docs.timescale.com/
- Best Practices: https://docs.timescale.com/timescaledb/latest/how-to-guides/

**FastAPI:**
- Tutorial: https://fastapi.tiangolo.com/tutorial/
- Async Guide: https://fastapi.tiangolo.com/async/

---

## ✅ Success Criteria

You've successfully completed Session 1 when:

1. You can activate the virtual environment
2. All dependencies install without errors
3. Docker containers run without issues
4. You can authenticate with Fyers and get a token
5. Token persists across restarts
6. You can retrieve your Fyers profile
7. FastAPI app runs and shows "Hello World"
8. You understand the project structure
9. CURRENT_SPRINT.md is updated
10. You feel confident to continue with Session 2

---

## 🤝 Getting Help

**If you get stuck:**

1. **Check the documentation** in docs/ folder
2. **Review .claudecontext** for coding standards
3. **Ask Claude Code** - be specific about the issue
4. **Check CURRENT_SPRINT.md** - you might have missed a dependency
5. **Google the error** - many issues are common
6. **Check Fyers API status** if API calls fail

**Common Claude Code prompts when stuck:**

```
I'm stuck on [specific issue]. Here's what I've tried:
1. [attempt 1]
2. [attempt 2]

The error is: [paste error]

Can you help diagnose and fix this?
```

---

## 🎉 Congratulations!

If you've made it this far, you've completed Session 1!

You now have:
- A working development environment
- Fyers API integration
- Docker containers running
- Foundation for the trading system

**Next up:** Data collection pipeline and database setup.

Keep building! 🚀

---

**Last Updated:** February 8, 2025
**Session:** 1 of ~12
**Progress:** ~8% of Phase 1
