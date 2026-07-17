from pathlib import Path

path = Path(__file__).with_name("agent_apply_data_integrity.py")
text = path.read_text(encoding="utf-8")
old = '''    replace_once(
        settings_path,
        "            resetFrontendAfterLocalDataReplacement();\\n",
        '            App.resetClientGeneration("secure_import");\\n',
    )
    replace_once(
        settings_path,
        "            resetFrontendAfterLocalDataReplacement();\\n",
        '            App.resetClientGeneration("clear_all_local_data");\\n',
    )
'''
new = '''    settings_content = read(settings_path)
    reset_call = "            resetFrontendAfterLocalDataReplacement();\\n"
    if settings_content.count(reset_call) != 2:
        raise AssertionError(
            f"{settings_path}: expected two replacement reset calls, "
            f"found {settings_content.count(reset_call)}"
        )
    settings_content = settings_content.replace(
        reset_call,
        '            App.resetClientGeneration("secure_import");\\n',
        1,
    )
    settings_content = settings_content.replace(
        reset_call,
        '            App.resetClientGeneration("clear_all_local_data");\\n',
        1,
    )
    write(settings_path, settings_content)
'''
if text.count(old) != 1:
    raise AssertionError(f"reset migration block count: {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
