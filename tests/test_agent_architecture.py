import autopilot_jobhunt.agent as agent_module


def test_root_agent_uses_single_agent_tool_handoff():
    tool_names = [getattr(tool, "__name__", type(tool).__name__) for tool in agent_module.root_agent.tools]

    assert "single coordinator" in agent_module.MASTER_INSTRUCTION
    assert "Current configuration summary" not in agent_module.MASTER_INSTRUCTION
    assert 'If the user sends a simple greeting such as "hi" or "hello"' in agent_module.MASTER_INSTRUCTION
    assert "For a simple greeting, use this exact response text:" in agent_module.MASTER_INSTRUCTION
    assert "Hello! I'm Autopilot Jobhunt, your session-aware job-hunt assistant." in agent_module.MASTER_INSTRUCTION
    assert (
        "I can help you organize and run a guided job search from discovery to tailored applications."
        in agent_module.MASTER_INSTRUCTION
    )
    assert (
        "We'll take it step by step and keep everything in this session focused on your targets."
        in agent_module.MASTER_INSTRUCTION
    )
    assert (
        "Workflow: configure job search -> search jobs -> score jobs -> pick top matches -> tailor application materials"
        in agent_module.MASTER_INSTRUCTION
    )
    assert (
        "To get started, send your resume text or upload a resume PDF, plus your target roles, target locations, and company career-page URLs."
        in agent_module.MASTER_INSTRUCTION
    )
    assert tool_names == [
        "configure_candidate_search",
        "scan_company_jobs",
        "score_and_rank_jobs",
        "tailor_application_materials",
        "export_results",
        "show_current_configuration",
        "show_scan_status",
    ]
    assert [type(plugin).__name__ for plugin in getattr(agent_module.app, "plugins", [])] == [
        "SaveFilesAsArtifactsPlugin"
    ]
    assert getattr(agent_module.root_agent, "sub_agents", []) == []
