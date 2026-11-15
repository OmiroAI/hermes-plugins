import pytest
from collaborator_drive.registry import grant_for, MissingGrant, validate


def test_chat_bound_grant_requires_exact_platform_and_chat(registry, source):
    entry=registry['collaborators'][0]
    entry['approved_chats']=[{'platform':source['platform'],'chat_id':'content-test'}]
    validate(registry)
    with pytest.raises(MissingGrant): grant_for(registry,source,'test-project')
    source['chat_id']='content-test'
    assert grant_for(registry,source,'test-project')['google_email'] == entry['google_email']
    source['platform']='other-platform'
    with pytest.raises(MissingGrant): grant_for(registry,source,'test-project')
