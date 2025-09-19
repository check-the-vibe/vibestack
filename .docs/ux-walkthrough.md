# VibeStack UX Walkthrough

This walkthrough covers the end-to-end user experience once the container is running locally on `http://localhost`. Use it to confirm the interface flows function as intended.

## 1. Landing Dashboard (`/ui/`)
1. Open `http://localhost/ui/` in a browser.
2. Verify the "VibeStack Session Control Center" header renders with no errors.
3. Confirm the sidebar exposes:
   - A **Template** selector defaulting to `bash`.
   - **Session name** pre-filled with a time-stamped suggestion.
   - Optional **Command override** and **Description** inputs.
   - **Launch session** button.
   - **Job name**, **Command to run**, and **Queue job** controls.
4. The main table should list existing sessions (empty on first run) and display columns: Name, Template, Type, Status, Created, Updated.

## 2. Create a Long-Running Session
1. In the sidebar, choose template `codex`.
2. Accept the suggested name (e.g., `codex-<HHMMSS>`) and click **Launch session**.
3. Expect a success toast and a new row in the sessions table with status `running`.
4. Confirm the session is auto-selected in the "Active session" dropdown.

## 3. Interact with Session Tabs
With the new session highlighted:
1. **Terminal tab**
   - Ensure an embedded terminal loads. The status line should echo the selected template.
   - Run a command (e.g., `ls`) and observe the output inline.
2. **Logs tab**
   - Logs should mirror terminal output, tailing the `console.log` file.
3. **Workspace tab**
   - If empty, create a file inside the terminal (`touch artifacts/test.txt`) and rerun tab to confirm listing.
4. **Streamlit tab**
   - Choose a file (e.g., `app.py`), edit text in the form, click **Save changes**, and confirm success notification.

## 4. Queue a One-Off Job
1. In the sidebar, enter a job command like `echo hello from job`.
2. Click **Queue job**.
3. Observe a toast, then check the **Job queue** table at the bottom for status transitions (`queued` → `running` → `completed`).

## 5. Session Management Page (`🗂️ Session Storage`)
1. Use the Streamlit sidebar to open the "🗂️ Session Storage" page.
2. Select the session you created.
3. Review metadata details and use **Download log** to verify the log file contents.
4. Click **Kill session**; confirm a success message and ensure the session’s status changes to `stopped` when you return to the dashboard.

## 6. Terminal Canvas (`💻 Terminal`)
1. Navigate to "💻 Terminal".
2. Confirm the active session from state is preselected.
3. Ensure the full-height embedded terminal attaches to that session and remains interactive.

## 7. Workspace Explorer (`📁 Workspace Explorer`)
1. Navigate to "📁 Workspace Explorer".
2. Switch contexts between `Streamlit`, `Vibestack package`, and `Sessions` using the dropdown.
3. Expand a file entry; verify the content viewer and **Download** button function.

## 8. External Terminal Verification
1. Open a new browser tab with `http://localhost/terminal/?arg=session&arg=workspace&arg=bash`.
2. Confirm it attaches to the default `workspace` session without errors.
3. Create another session using `?arg=create&arg=claude&arg=claude-dev` and ensure the UX displays the creation banner before attaching.

Completing these steps validates the user-facing milestones for session creation, monitoring, job execution, file editing, and terminal access.
