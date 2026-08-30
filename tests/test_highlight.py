import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.highlight import annotate_highlights


def test_annotate_highlights_delegates_to_check_keys_process():
    with patch("src.highlight.process", return_value="cleaned **marked** text") as mock_process:
        result = annotate_highlights("raw tweet text")

    mock_process.assert_called_once_with("raw tweet text")
    assert result == "cleaned **marked** text"
