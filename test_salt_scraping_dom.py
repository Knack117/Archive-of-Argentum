import pytest

from app import DeckValidator


SAMPLE_HTML = """
<html>
  <body>
    <ul>
      <li class="salt-card" data-card-name="Stasis">
        <span class="card-name">Stasis</span>
        <span class="salt-score">Salt Score: 3.06</span>
      </li>
      <li class="salt-card">
        <a class="card" href="/cards/winter-orb">
          Winter Orb
        </a>
        <div class="stats">
          <span class="salt-label">Salt Score: 2.96</span>
        </div>
      </li>
      <li class="salt-card">
        <div class="content">
          <strong>Armageddon</strong>
          <div>Salt Score: 2.67</div>
        </div>
      </li>
    </ul>
  </body>
</html>
"""


@pytest.mark.asyncio
async def test_parse_salt_scores_from_dom_extracts_names():
    validator = DeckValidator()
    scores = validator._parse_salt_scores_from_dom(SAMPLE_HTML)

    assert scores["Stasis"] == pytest.approx(3.06)
    assert scores["Winter Orb"] == pytest.approx(2.96)
    assert scores["Armageddon"] == pytest.approx(2.67)
    assert len(scores) == 3
