from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from profsearch.config import Settings
from profsearch.scraping.client import AsyncHtmlClient
from profsearch.scraping.extractors import extract_pagination_urls, extract_profile_details, extract_roster_entries
from profsearch.scraping.normalize import classify_title


def test_extract_roster_entries_uses_parser_hint() -> None:
    html = Path("tests/fixtures/sample_roster_page.html").read_text(encoding="utf-8")
    entries = extract_roster_entries(html, "https://example.edu/faculty", parser_hint="mit_faculty_cards")
    assert len(entries) == 2
    assert entries[0].name == "Jane Doe"
    assert entries[0].email == "jane@university.edu"
    assert entries[0].profile_url == "https://example.edu/faculty/jane-doe"


def test_classify_title_respects_exclusions() -> None:
    assert classify_title("Associate Professor of Physics").status == "verified"
    assert classify_title("Postdoctoral Fellow").status == "excluded"
    assert classify_title("Adjunct Professor").status == "ambiguous"


def test_extract_pagination_urls_finds_same_path_pages() -> None:
    html = """
    <html><body>
      <a href="/people/faculty?page=1">2</a>
      <a href="/people/faculty?page=2#main">3</a>
      <a href="/people/staff?page=1">staff</a>
    </body></html>
    """
    urls = extract_pagination_urls(html, "https://example.edu/people/faculty")
    assert urls == [
        "https://example.edu/people/faculty?page=1",
        "https://example.edu/people/faculty?page=2",
    ]


def test_extract_profile_details_reads_stanford_style_title() -> None:
    html = """
    <html><body>
      <h1>Philip H. Bucksbaum</h1>
      <div class="profile faculty field-position string label-hidden">
        Professor of Applied Physics, Physics, and Photon Science
      </div>
      <div class="su-person-long-bio">
        Philip Bucksbaum studies ultrafast optics, x-ray science, and atomic physics.
      </div>
    </body></html>
    """
    details = extract_profile_details(html, "https://example.edu/profile/7")
    assert details.title == "Professor of Applied Physics, Physics, and Photon Science"
    assert details.profile_text is not None
    assert "ultrafast optics" in details.profile_text


def test_extract_roster_entries_reads_caltech_people_listing() -> None:
    html = """
    <html><body>
      <div class="person-listing">
        <div class="person-listing__person-row">
          <a class="person-listing__person-row__wrapper-link" href="/people/rana-adhikari">
            <span class="sr-only">Rana Adhikari</span>
          </a>
          <div class="person-listing__summary">
            <div class="person-listing__summary__title">Rana Adhikari</div>
            <div class="person-listing__summary__faculty-title">Professor of Physics</div>
          </div>
        </div>
      </div>
    </body></html>
    """
    entries = extract_roster_entries(
        html,
        "https://www.pma.caltech.edu/people?cat_one=Professorial+Faculty&cat_two=Physics",
        parser_hint="caltech_people_listing",
    )
    assert len(entries) == 1
    assert entries[0].name == "Rana Adhikari"
    assert entries[0].title == "Professor of Physics"
    assert entries[0].profile_url == "https://www.pma.caltech.edu/people/rana-adhikari"


def test_extract_roster_entries_reads_yale_people_table() -> None:
    html = """
    <html><body>
      <table class="views-table">
        <tr>
          <td class="views-field views-field-picture"></td>
          <td class="views-field views-field-name">
            <a href="/people/charles-ahn" class="username">Charles Ahn</a><br />
            John C. Malone Professor of Applied Physics and Professor of Mechanical Engineering and of Physics<br />
            <a href="mailto:charles.ahn@yale.edu">charles.ahn@yale.edu</a>
          </td>
        </tr>
      </table>
    </body></html>
    """
    entries = extract_roster_entries(html, "https://physics.yale.edu/people/faculty", parser_hint="yale_people_table")
    assert len(entries) == 1
    assert entries[0].name == "Charles Ahn"
    assert entries[0].title == "John C. Malone Professor of Applied Physics and Professor of Mechanical Engineering and of Physics"
    assert entries[0].email == "charles.ahn@yale.edu"


def test_extract_roster_entries_reads_uchicago_people_list() -> None:
    html = """
    <html><body>
      <li class="mix faculty">
        <a href="https://physics.uchicago.edu/people/profile/edward-blucher/">
          <div class="people_img"><h5>Edward Blucher</h5></div>
          <div class="people_content">
            <h3>
              <span>Edward Blucher</span>
              <b>Professor</b>
            </h3>
          </div>
        </a>
      </li>
    </body></html>
    """
    entries = extract_roster_entries(
        html,
        "https://physics.uchicago.edu/people/",
        parser_hint="uchicago_people_list",
    )
    assert len(entries) == 1
    assert entries[0].name == "Edward Blucher"
    assert entries[0].title == "Professor"
    assert entries[0].profile_url == "https://physics.uchicago.edu/people/profile/edward-blucher/"


def test_extract_roster_entries_reads_ucsb_directory_rows() -> None:
    html = """
    <html><body>
      <div class="views-row">
        <div><div class="group-first"><a href="/people/prateek-agrawal"><img alt="Image of Prateek Agrawal" /></a></div></div>
        <div><div class="group-second">
          <h3><a href="/people/prateek-agrawal">Prateek Agrawal</a></h3>
          Associate Professor<br />
          <a href="mailto:prateekagrawal@ucsb.edu">prateekagrawal@ucsb.edu</a>
        </div></div>
        <div><div class="group-third">Exploring theoretical physics beyond the standard models of particle physics and cosmology.</div></div>
      </div>
    </body></html>
    """
    entries = extract_roster_entries(
        html,
        "https://www.physics.ucsb.edu/people/faculty",
        parser_hint="ucsb_directory_rows",
    )
    assert len(entries) == 1
    assert entries[0].name == "Prateek Agrawal"
    assert entries[0].title == "Associate Professor"
    assert entries[0].email == "prateekagrawal@ucsb.edu"
    assert entries[0].profile_text is not None
    assert "particle physics and cosmology" in entries[0].profile_text


def test_extract_roster_entries_reads_princeton_content_list() -> None:
    html = """
    <html><body>
      <div class="content-list-item">
        <div class="content-list-item-details">
          <span class="field field--name-title"><a href="/people/dmitry-abanin">Dmitry Abanin</a></span>
          <div class="field field--name-field-ps-people-position field--type-string field--label-hidden field__item">Professor of Physics</div>
          <div class="field field--name-field-ps-people-research-area"><div class="field__item">Condensed Matter Theory</div></div>
        </div>
      </div>
    </body></html>
    """
    entries = extract_roster_entries(html, "https://phy.princeton.edu/people/faculty", parser_hint="princeton_content_list")
    assert len(entries) == 1
    assert entries[0].name == "Dmitry Abanin"
    assert entries[0].title == "Professor of Physics"
    assert entries[0].profile_url == "https://phy.princeton.edu/people/dmitry-abanin"


def test_extract_roster_entries_reads_penn_people_rows() -> None:
    html = """
    <html><body>
      <div class="row people-list views-row">
        <h3><a href="/people/standing-faculty/vijay-balasubramanian">Vijay Balasubramanian</a></h3>
        <p class="title"><span class="title">Cathy and Marc Lasry Professor</span></p>
        <p class="contact"><span class="email"><a href="mailto:vijay@physics.upenn.edu">vijay@physics.upenn.edu</a></span></p>
        <p>2N3A, David Rittenhouse Laboratory <span class="website"><a href="/people/standing-faculty/vijay-balasubramanian">Read Bio</a></span></p>
      </div>
    </body></html>
    """
    entries = extract_roster_entries(html, "https://www.physics.upenn.edu/people/standing-faculty", parser_hint="penn_people_rows")
    assert len(entries) == 1
    assert entries[0].name == "Vijay Balasubramanian"
    assert entries[0].title == "Cathy and Marc Lasry Professor"
    assert entries[0].email == "vijay@physics.upenn.edu"


def test_extract_roster_entries_reads_ucla_faculty_table() -> None:
    html = """
    <html><body>
      <table>
        <tr>
          <td>
            <h5>Paulo Alves</h5>
            <p>
              Assistant Professor<br />
              Plasma<br />
              Office: PAB 4-909<br />
              Email:
              <script>
                var name = "epalves";
                var domain = "physics.ucla.edu";
              </script>
              <a href="https://picksc.physics.ucla.edu/index.html">Website</a>
            </p>
          </td>
        </tr>
      </table>
    </body></html>
    """
    entries = extract_roster_entries(html, "https://www.pa.ucla.edu/faculty.html", parser_hint="ucla_faculty_table")
    assert len(entries) == 1
    assert entries[0].name == "Paulo Alves"
    assert entries[0].title == "Assistant Professor"
    assert entries[0].email == "epalves@physics.ucla.edu"
    assert entries[0].profile_url == "https://picksc.physics.ucla.edu/index.html"


def test_extract_roster_entries_reads_umd_k2_faculty() -> None:
    html = """
    <html><body>
      <div class="catItemView groupPrimary">
        <h4 class="catItemTitle"><a href="/people/faculty/current/item/123-james-drake">James Drake</a></h4>
        <div class="catItemExtraFields">
          <span class="catItemExtraFieldsLabel">Title</span>
          <span class="catItemExtraFieldsValue">Distinguished University Professor</span>
          <span class="catItemExtraFieldsLabel">E-mail</span>
          <span class="catItemExtraFieldsValue"><a href="mailto:drake@umd.edu">drake@umd.edu</a></span>
        </div>
      </div>
    </body></html>
    """
    entries = extract_roster_entries(
        html,
        "https://umdphysics.umd.edu/people/faculty.html",
        parser_hint="umd_k2_faculty",
    )
    assert len(entries) == 1
    assert entries[0].name == "James Drake"
    assert entries[0].title == "Distinguished University Professor"
    assert entries[0].email == "drake@umd.edu"
    assert entries[0].profile_url == "https://umdphysics.umd.edu/people/faculty/current/item/123-james-drake"


def test_extract_roster_entries_reads_washington_views_rows() -> None:
    html = """
    <html><body>
      <div class="thin-top-border-gray views-row">
        <div class="views-field views-field-title"><h3 class="field-content"><a href="/people/jiun-haw-chu">Jiun-Haw Chu</a></h3></div>
        <div class="views-field views-field-field-job-title"><div class="field-content">Professor</div></div>
        <span class="views-field views-field-field-email"><span class="field-content"><a href="mailto:jhchu@uw.edu">jhchu@uw.edu</a></span></span>
        <div class="views-field views-field-term-node-tid"><span class="field-content"><a href="/fields/condensed-matter">Condensed Matter</a></span></div>
      </div>
    </body></html>
    """
    entries = extract_roster_entries(
        html,
        "https://phys.washington.edu/people/faculty",
        parser_hint="washington_views_rows",
    )
    assert len(entries) == 1
    assert entries[0].name == "Jiun-Haw Chu"
    assert entries[0].title == "Professor"
    assert entries[0].email == "jhchu@uw.edu"
    assert entries[0].profile_text == "Condensed Matter"


def test_extract_roster_entries_reads_gatech_people_grid() -> None:
    html = """
    <html><body>
      <div class="people">
        <ul class="grid">
          <li><div><h3 class="p-name"><a href="/user/david-ballantyne">David Ballantyne</a></h3></div></li>
        </ul>
      </div>
    </body></html>
    """
    entries = extract_roster_entries(
        html,
        "https://physics.gatech.edu/people/professors",
        parser_hint="gatech_people_grid",
    )
    assert len(entries) == 1
    assert entries[0].name == "David Ballantyne"
    assert entries[0].title is None
    assert entries[0].profile_url == "https://physics.gatech.edu/user/david-ballantyne"


def test_extract_profile_details_reads_gatech_profile_title() -> None:
    html = """
    <html><body>
      <article id="node-user" class="gt_people--view-mode--full user-profile">
        <div class="gtppl-header">
          <div class="gtppl-header-txt">
            <h1>David Ballantyne</h1>
            <p>Professor / Associate Chair for Academic Programs</p>
          </div>
        </div>
        <dl>
          <dt class="-email">Email</dt>
          <dd class="-email"><a href="mailto:david.ballantyne@physics.gatech.edu">david.ballantyne@physics.gatech.edu</a></dd>
        </dl>
        <div class="field-name-body">
          <p>My research concentrates on topics in high-energy astrophysics.</p>
        </div>
      </article>
    </body></html>
    """
    details = extract_profile_details(html, "https://physics.gatech.edu/user/david-ballantyne")
    assert details.title == "Professor / Associate Chair for Academic Programs"
    assert details.email == "david.ballantyne@physics.gatech.edu"
    assert details.profile_text is not None
    assert "high-energy astrophysics" in details.profile_text


def test_extract_roster_entries_reads_northwestern_people_articles() -> None:
    html = """
    <html><body>
      <article class="people">
        <div class="people-wrap">
          <div class="people-content">
            <h3><a href="jason-wang.html">Jason Wang</a></h3>
            <p class="title">Assistant Professor</p>
            <p>Office location: 1800 Sherman #8059<br /><a href="mailto:jason.wang@northwestern.edu">jason.wang@northwestern.edu</a></p>
          </div>
        </div>
      </article>
    </body></html>
    """
    entries = extract_roster_entries(
        html,
        "https://physics.northwestern.edu/people/faculty/core-faculty/",
        parser_hint="northwestern_people_articles",
    )
    assert len(entries) == 1
    assert entries[0].name == "Jason Wang"
    assert entries[0].title == "Assistant Professor"
    assert entries[0].email == "jason.wang@northwestern.edu"
    assert entries[0].profile_url == "https://physics.northwestern.edu/people/faculty/core-faculty/jason-wang.html"


def test_extract_roster_entries_reads_wisc_faculty_cards() -> None:
    html = """
    <html><body>
      <div class="faculty-member column small-12 medium-3">
        <div class="faculty-member-content">
          <a class="faculty-name" href="https://www.physics.wisc.edu/directory/woods-benjamin/">Benjamin Woods</a>
          <p class="position-title"><span class="screen-reader-text">Position title: </span>Assistant Professor</p>
        </div>
      </div>
    </body></html>
    """
    entries = extract_roster_entries(
        html,
        "https://www.physics.wisc.edu/people/faculty/",
        parser_hint="wisc_faculty_cards",
    )
    assert len(entries) == 1
    assert entries[0].name == "Benjamin Woods"
    assert entries[0].title == "Assistant Professor"
    assert entries[0].profile_url == "https://www.physics.wisc.edu/directory/woods-benjamin/"


def test_async_html_client_retries_with_insecure_tls(monkeypatch) -> None:
    settings = Settings()
    client = AsyncHtmlClient(settings)
    request = httpx.Request("GET", "https://pa.ucla.edu/faculty.html")

    async def raise_tls_error(url: str) -> httpx.Response:
        raise httpx.ConnectError("CERTIFICATE_VERIFY_FAILED", request=request)

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.verify = kwargs.get("verify", True)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str) -> httpx.Response:
            assert self.verify is False
            return httpx.Response(200, text="<html>ok</html>", request=httpx.Request("GET", url))

    monkeypatch.setattr(client._client, "get", raise_tls_error)
    monkeypatch.setattr("profsearch.scraping.client.httpx.AsyncClient", FakeAsyncClient)

    response = asyncio.run(client.fetch("https://pa.ucla.edu/faculty.html", {"ucla.edu"}))
    assert response.status_code == 200
    assert response.url == "https://pa.ucla.edu/faculty.html"

    asyncio.run(client.aclose())
