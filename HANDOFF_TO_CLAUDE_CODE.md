# 🚀 Handoff to Claude Code Desktop App

This file contains the **exact prompts** to use when starting development with Claude Code.

---

## ✅ Pre-Flight Checklist

Before you begin:

- [ ] Claude Code desktop app is installed and running
- [ ] Python 3.11+ is installed
- [ ] Docker Desktop is installed and running
- [ ] You have your Fyers API credentials ready
- [ ] All project files are in the `nifty-ai-trader/` directory

---

## 📂 Step 1: Open Project in Claude Code

1. **Launch Claude Code desktop app**
2. **Click "Open Folder"** (or `Cmd/Ctrl + O`)
3. **Navigate to `nifty-ai-trader/`** directory
4. **Click "Select Folder"**
5. **Wait** for Claude Code to index the files (~5-10 seconds)

---

## 💬 Step 2: Initial Prompt (Copy & Paste This)

Once the folder is indexed, **copy and paste this exact prompt** into Claude Code:

```
Hi! I'm building an AI-driven automated Nifty options trading system.

Please read these context files in order:
1. PROJECT_BRIEF.md - High-level project overview and architecture
2. CURRENT_SPRINT.md - Current sprint tasks for Week 1-2
3. .claudecontext - Coding standards and guidelines

After reading these files:
1. Confirm you understand the project scope and goals
2. Summarize the tech stack we're using
3. Tell me which task we should start with from CURRENT_SPRINT.md

Then we'll begin Sprint 1, Task 1.1: Project Setup.

Ready?
```

---

## 💬 Step 3: After Claude Confirms (Next Prompt)

After Claude Code reads the files and confirms understanding, use this prompt:

```
Perfect! Let's start Task 1.1: Project Setup and Environment Configuration.

Please create the complete directory structure as outlined in PROJECT_BRIEF.md.

The structure should include:
- src/ with all subdirectories (api, data, integrations, database, etc.)
- tests/ with unit and integration subdirectories
- scripts/ for utility scripts
- docs/ for documentation
- docker/ for containerization
- config/ for configuration files

Also create all necessary __init__.py files to make packages importable.

After creating the structure, show me a tree view of what you created.
```

---

## 💬 Step 4: Create Dependencies (Next Prompt)

After directory structure is created:

```
Great! Now let's create the dependency files.

Please create:

1. requirements.txt with these core dependencies:
   - fastapi[all]>=0.104.0
   - fyers-apiv3>=3.1.5
   - pandas>=2.0.0
   - numpy>=1.24.0
   - psycopg2-binary>=2.9.9
   - sqlalchemy>=2.0.0
   - redis>=5.0.0
   - python-dotenv>=1.0.0
   - pydantic>=2.5.0
   - pydantic-settings>=2.1.0
   - aiohttp>=3.9.0
   - asyncpg>=0.29.0
   - celery>=5.3.0
   - ta-lib
   - scikit-learn>=1.3.0
   - structlog>=23.2.0

2. requirements-dev.txt with development tools:
   - pytest>=7.4.0
   - pytest-asyncio>=0.21.0
   - pytest-cov>=4.1.0
   - black>=23.11.0
   - isort>=5.12.0
   - mypy>=1.7.0
   - flake8>=6.1.0
   - pre-commit>=3.5.0

3. pyproject.toml with project metadata following modern Python standards

Show me the files when done.
```

---

## 💬 Step 5: Docker Setup (Next Prompt)

```
Excellent! Now let's set up Docker containers.

Please create docker/docker-compose.yml with:

1. TimescaleDB service:
   - Image: timescale/timescaledb:latest-pg15
   - Port: 5432
   - Environment variables for user, password, database
   - Volume for data persistence
   - Health check

2. Redis service:
   - Image: redis:7-alpine
   - Port: 6379
   - Volume for data persistence
   - Health check

3. Network configuration to allow services to communicate

Use environment-friendly settings (read from .env) and include restart policies.

Show me the docker-compose.yml when done.
```

---

## 💬 Step 6: FastAPI Setup (Next Prompt)

```
Perfect! Now let's create the basic FastAPI application.

Please create src/api/main.py with:

1. FastAPI app initialization
2. CORS middleware
3. Health check endpoint at /api/v1/health
4. Lifespan context manager for startup/shutdown
5. Basic error handling
6. Logger configuration
7. Proper async setup

Also create src/config/settings.py using pydantic-settings to load configuration from .env file.

Follow the coding standards from .claudecontext (type hints, docstrings, etc.)

Show me both files when done.
```

---

## 💬 Step 7: Fyers Integration (Next Prompt)

```
Great! Now let's move to Task 1.2: Fyers API Integration.

This is critical - please read the Fyers API documentation context carefully.

Please create src/integrations/fyers_client.py with a FyersClient class that includes:

1. OAuth 2.0 authentication flow:
   - authenticate() -> returns authorization URL
   - get_access_token(auth_code: str) -> exchanges code for token
   - refresh_token() -> refreshes expired token
   
2. Token management:
   - Save tokens to a secure file (JSON)
   - Load tokens on initialization
   - Auto-refresh when expired
   
3. Connection management:
   - is_authenticated() -> checks token validity
   - get_profile() -> fetches user profile (connection test)
   - Proper session handling
   
4. Rate limiting:
   - Respect Fyers API limits (1 req/sec for historical data)
   - Implement request queue
   
5. Error handling:
   - Custom exceptions for different error types
   - Retry logic with exponential backoff
   - Comprehensive logging

6. Follow .claudecontext standards:
   - Type hints on all methods
   - Google-style docstrings
   - Async/await for all I/O
   - Structured logging using structlog

Reference: https://api-docs.fyers.in/

This is a critical component - take your time to do it right.

Show me the code when done, and explain the key design decisions.
```

---

## 💬 Step 8: Test Script (Next Prompt)

After FyersClient is created:

```
Excellent work on the FyersClient! Now let's test it.

Please create scripts/test_fyers_auth.py that:

1. Loads credentials from .env file
2. Creates a FyersClient instance
3. Initiates the OAuth flow
4. Prints the authorization URL clearly
5. Prompts user to visit URL and authenticate
6. Waits for user to paste the auth code
7. Exchanges auth code for access token
8. Saves the token
9. Fetches and displays user profile
10. Confirms successful authentication

Make it user-friendly with:
- Clear step-by-step instructions
- Colored output (using colorama if needed)
- Error handling with helpful messages
- Success confirmation

Show me the script when done.
```

---

## 🔄 Iterative Development Pattern

After completing each component, use this pattern:

### Review and Enhance

```
Thanks for creating [component name]. Let me review it.

[After reviewing]

I'd like to enhance it with:
1. [Specific enhancement 1]
2. [Specific enhancement 2]
3. [Specific enhancement 3]

Please update the code with these improvements.
```

### Add Tests

```
Now let's create tests for [component name].

Please create tests/test_[component_name].py with:

1. Unit tests for core functionality
2. Mock external dependencies (Fyers API)
3. Test error handling scenarios
4. Test edge cases

Use pytest and follow AAA pattern (Arrange, Act, Assert).
```

### Documentation

```
Please add comprehensive documentation for [component name]:

1. Update docstrings with examples
2. Create docs/[component_name].md with:
   - Overview and purpose
   - Usage examples
   - Configuration options
   - Common issues and solutions

Follow the style in PROJECT_BRIEF.md.
```

---

## 🐛 Common Issues and Solutions

### Issue: Claude Code Can't Find Files

**Prompt:**
```
I don't see [filename] in the project. Can you:
1. Run: ls -la
2. Show me the current directory structure
3. Verify the file exists and is in the right location
```

### Issue: Code Not Following Standards

**Prompt:**
```
Please review the code you just created against .claudecontext.

Specifically check:
1. Are all functions type-hinted?
2. Are there Google-style docstrings?
3. Is error handling comprehensive?
4. Are we using async/await for I/O?
5. Is structured logging being used?

Update the code to fix any violations.
```

### Issue: Need to Understand a Decision

**Prompt:**
```
Can you explain why you [specific decision]?

Also, what are the alternatives and their tradeoffs?
```

### Issue: Integration Not Working

**Prompt:**
```
The integration between [component A] and [component B] isn't working.

Here's the error: [paste error]

Can you:
1. Identify the issue
2. Explain what's wrong
3. Fix the integration
4. Add tests to prevent this in future
```

---

## 📊 Progress Tracking

After each major component, update progress:

```
Great work! Let's update CURRENT_SPRINT.md.

Please:
1. Move completed tasks from "Todo" to "Completed"
2. Update the progress percentage
3. Add any notes about what we built
4. Update time spent
5. Note any blockers or issues encountered

Show me the updated CURRENT_SPRINT.md when done.
```

---

## 🎯 Session End Prompt

At the end of each session:

```
Let's wrap up this session and document our progress.

Please:

1. Update CURRENT_SPRINT.md with:
   - Completed tasks
   - In-progress tasks
   - Time spent
   - Blockers/issues
   - Notes about decisions made

2. Create SESSION_[NUMBER]_SUMMARY.md with:
   - Date and duration
   - What we accomplished
   - What's working and tested
   - What needs more work
   - Priorities for next session
   - Any important notes or decisions

3. Show me a summary of what we achieved today

This helps us resume efficiently next time.
```

---

## 🔄 Starting a New Session

When you return for the next session:

```
Hi! Continuing from Session [NUMBER].

Please read:
1. CURRENT_SPRINT.md - Updated status
2. SESSION_[LAST_NUMBER]_SUMMARY.md - What we did last time

Then:
1. Summarize what we completed
2. Identify what we should work on next
3. Ask any questions about unclear items

Let's continue where we left off!
```

---

## 💡 Pro Tips

### 1. One Task at a Time
Don't try to build everything at once. Complete one task fully (code + tests + docs) before moving to the next.

### 2. Verify Before Proceeding
After each component:
```
Before we move on, let me verify this works.

[test manually]

It works! Let's continue with [next task].
```

### 3. Ask for Explanations
Don't hesitate to ask "why":
```
Why did you choose [approach X] instead of [approach Y]?
What are the tradeoffs?
```

### 4. Reference Previous Work
```
Using the FyersClient we created earlier, let's now build
the OHLCCollector that will use it for fetching market data.
```

### 5. Request Alternatives
```
This works, but I'm curious - what other approaches could we use?
What would be the pros/cons of each?
```

---

## ✅ Quality Checklist

Before considering a component "done", verify:

- [ ] Code follows .claudecontext standards
- [ ] All functions have type hints
- [ ] All functions have docstrings
- [ ] Error handling is comprehensive
- [ ] Logging is implemented
- [ ] Tests are written and passing
- [ ] Documentation is updated
- [ ] Code is committed to git
- [ ] CURRENT_SPRINT.md is updated

---

## 🎓 Learning Mode

If you want to learn while building:

```
Before implementing [feature], can you explain:
1. The high-level approach
2. Key concepts I should understand
3. Potential pitfalls to avoid
4. Best practices for this type of problem

Then we'll implement it together.
```

---

## 🚨 Emergency Commands

### Stop and Refactor

```
Wait - before we continue, I think we should refactor [component].

Current issues:
1. [Issue 1]
2. [Issue 2]

Can you suggest a better approach and implement it?
```

### Start Over

```
Let's restart [component] with a better approach.

Delete the current implementation and create a new one that:
1. [Requirement 1]
2. [Requirement 2]
3. [Requirement 3]
```

### Review Everything

```
Can you review all the code we've written so far and identify:
1. Potential bugs
2. Performance issues
3. Security concerns
4. Code quality issues
5. Missing error handling

Provide a prioritized list of improvements.
```

---

## 🎉 You're Ready!

You now have everything you need to start building with Claude Code!

**Remember:**
- Be specific in your prompts
- Build incrementally
- Test as you go
- Document everything
- Review before proceeding
- Ask questions when unclear

**Start with the Initial Prompt** (Step 2 above) and work through systematically.

Good luck! 🚀

---

**Quick Reference:**
- First prompt: Ask Claude to read PROJECT_BRIEF.md, CURRENT_SPRINT.md, .claudecontext
- Start with Task 1.1: Project Setup
- Follow the prompts in order
- Update CURRENT_SPRINT.md after each task
- End each session with a summary

---

*Last Updated: February 8, 2025*
