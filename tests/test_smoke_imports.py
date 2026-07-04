import autopilot_jobhunt.agent as agent_module
import autopilot_jobhunt.web_app as web_app_module


def test_import_smoke():
    assert agent_module.root_agent.name == "autopilot_jobhunt"
    assert type(web_app_module.app).__name__
