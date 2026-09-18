from capsize_fastmail.preprocessing import (
    classify_automated,
    strip_quoted_content,
)
from capsize_fastmail.provider import EmailMessage


def _message(from_address: str = "", subject: str = "") -> EmailMessage:
    return EmailMessage(
        provider_id="1",
        thread_id="1",
        mailbox_role="",
        from_address=from_address,
        subject=subject,
    )


def test_strip_quoted_content_removes_on_wrote_block() -> None:
    body = "My reply.\n\nOn Jan 1, 2026, Alice wrote:\n> quoted text"
    assert strip_quoted_content(body) == "My reply."


def test_strip_quoted_content_removes_signature() -> None:
    body = "My reply.\n--\nAlice\nSent from my phone"
    assert strip_quoted_content(body) == "My reply."


def test_strip_quoted_content_removes_leading_quote_markers() -> None:
    body = "Reply line.\n> quoted line one\n> quoted line two"
    assert strip_quoted_content(body) == "Reply line."


def test_strip_quoted_content_handles_empty() -> None:
    assert strip_quoted_content("") == ""
    assert strip_quoted_content(None) == ""  # type: ignore[arg-type]


def test_classify_automated_by_sender() -> None:
    assert classify_automated(_message(from_address="no-reply@shop.com"))


def test_classify_automated_by_domain() -> None:
    assert classify_automated(
        _message(from_address="updates@mailchimp.com")
    )


def test_classify_automated_by_subject() -> None:
    assert classify_automated(
        _message(
            from_address="orders@shop.com",
            subject="Your order has shipped",
        )
    )


def test_classify_automated_false_for_personal_mail() -> None:
    assert not classify_automated(
        _message(from_address="alice@example.com", subject="Dinner Friday?")
    )
