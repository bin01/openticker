---- MODULE Workbench ----
\* Tick's workbench with Claude Code: the toolbox install (workbench.build/_build/python), the switch that turns the
\* workbench off when Claude Code's sandbox doesn't start (workbench.claude_ready/claude_failed), the fallback in
\* runs._work, and what the prompt promises (workbench.note via agent.build_prompt). SKILL.md has the full map.

CONSTANT SandboxWorks     \* whether Claude Code's macOS sandbox starts on this Mac

VARIABLES
    toolbox,    \* workbench.state["toolbox"]; "ready" also means TOOLBOX/.ready exists on disk
    onDisk,     \* TOOLBOX/.ready exists (survives a restart)
    toolWait,   \* a failed install is less than RETRY_AFTER old
    claudeOk,   \* workbench.state["claude_ok"]
    claudeWait, \* claude_off is less than RETRY_AFTER old
    agent,      \* how Claude Code behaves right now
    oddSeen,    \* an unexplained quick error happened since the switch was last on
    last        \* what the last answer had

vars == <<toolbox, onDisk, toolWait, claudeOk, claudeWait, agent, oddSeen, last>>

\* agent: "ok"; "plain" = an error that says what it is (signed out, usage limit, overloaded, offline: agent.PLAIN_FAILURE);
\*        "odd" = any other error inside 30 seconds with no text, which _work can't tell from a sandbox that didn't start
\* last:  "none"; "bench" = with the workbench and the note that promises scipy and matplotlib;
\*        "early" = with the workbench and the note for a toolbox still being set up; "plain" = without the workbench;
\*        "failed" = no answer

Init == toolbox = "building" /\ onDisk = FALSE /\ toolWait = FALSE /\ claudeOk = TRUE /\ claudeWait = FALSE
    /\ agent = "ok" /\ oddSeen = FALSE /\ last = "none"

\* _build: uv venv + pip install, then write TOOLBOX/.ready and state toolbox="ready"
ToolboxBuilt == toolbox = "building" /\ toolbox' = "ready" /\ onDisk' = TRUE
    /\ UNCHANGED <<toolWait, claudeOk, claudeWait, agent, oddSeen, last>>
\* _build: the install fails (offline, no space); state toolbox="failed", failed_at=now
ToolboxFails == toolbox = "building" /\ toolbox' = "failed" /\ toolWait' = TRUE
    /\ UNCHANGED <<onDisk, claudeOk, claudeWait, agent, oddSeen, last>>

\* time passes: RETRY_AFTER (an hour) since the install failed, or since the sandbox failed
AnHourPasses == (toolWait \/ claudeWait) /\ toolWait' = FALSE /\ claudeWait' = FALSE
    /\ UNCHANGED <<toolbox, onDisk, claudeOk, agent, oddSeen, last>>

\* Claude Code's state changes on its own: signed out, at its limit, a crash, and back
AgentChanges == \E a \in {"ok", "plain", "odd"} \ {agent} : agent' = a
    /\ UNCHANGED <<toolbox, onDisk, toolWait, claudeOk, claudeWait, oddSeen, last>>

\* ---- one question to Tick with Claude Code: runs._work

\* bench = claude_ready(): claude_ok comes back on once an hour has passed
BenchOn == claudeOk \/ ~claudeWait
\* workbench.build() at the start of _work: a failed install is tried again after an hour; python() finds a ready one
ToolboxAfterBuild == IF onDisk THEN "ready"
                     ELSE IF toolbox = "failed" /\ ~toolWait THEN "building" ELSE toolbox
\* the note is chosen by python() when the prompt is built
Note(tb) == IF tb = "ready" THEN "bench" ELSE "early"

YouAsk ==
    /\ toolbox' = (IF BenchOn THEN ToolboxAfterBuild ELSE toolbox)
    /\ UNCHANGED <<onDisk, toolWait>>
    /\ IF ~BenchOn
       THEN \* agent.Run without a workspace
            last' = (IF agent = "ok" THEN "plain" ELSE "failed") /\ UNCHANGED <<claudeOk, claudeWait, oddSeen, agent>>
       ELSE IF agent = "ok" /\ SandboxWorks
       THEN last' = Note(toolbox') /\ claudeOk' = TRUE /\ UNCHANGED <<claudeWait, oddSeen, agent>>
       ELSE IF agent = "plain"
       THEN \* quick_fail is False for a plain failure: the error is shown, the workbench stays on
            last' = "failed" /\ claudeOk' = TRUE /\ UNCHANGED <<claudeWait, oddSeen, agent>>
       ELSE \* sandbox_failed(error) or quick_fail: claude_failed(), then go(None, None) without the workbench
            /\ claudeOk' = FALSE /\ claudeWait' = TRUE
            /\ oddSeen' = (agent = "odd")
            /\ last' = (IF agent = "ok" THEN "plain" ELSE "failed")
            /\ UNCHANGED agent

\* quit and start again: state is rebuilt (claude_ok True, toolbox "missing"), then workbench.ensure() -> build()
Restart == toolbox' = (IF onDisk THEN "ready" ELSE "building") /\ toolWait' = FALSE
    /\ claudeOk' = TRUE /\ claudeWait' = FALSE /\ oddSeen' = FALSE /\ last' = "none"
    /\ UNCHANGED <<onDisk, agent>>

Next == ToolboxBuilt \/ ToolboxFails \/ AnHourPasses \/ AgentChanges \/ YouAsk \/ Restart

Spec == Init /\ [][Next]_vars

\* ---- Rules

\* The workbench is switched off only after the sandbox failed, or after an error that could be the sandbox failing,
\* never after one that says plainly what went wrong (signed out, at the limit).
OffOnlyAfterSandboxTrouble == ~claudeOk => (~SandboxWorks \/ oddSeen)

\* Tick is promised scipy, matplotlib and pip only when the toolbox is installed.
PromisedToolsExist == last = "bench" => toolbox = "ready"

====
