import copy
import json

import pytest

from scripts.teardown import prepare_snapshot_policy, snapshot_template


@pytest.mark.parametrize("choice, policy", [("keep", "Snapshot"), ("delete", "Delete")])
def test_snapshot_choice_changes_only_rds_deletion_policy(choice, policy):
    original = {"Resources": {
        "Db": {"Type": "AWS::RDS::DBInstance", "Properties": {"Engine": "postgres"},
               "DeletionPolicy": "Snapshot", "UpdateReplacePolicy": "Snapshot"},
        "Storage": {"Type": "AWS::S3::Bucket", "DeletionPolicy": "Delete"}}}
    before = copy.deepcopy(original)
    modified = snapshot_template(original, choice)
    assert modified["Resources"]["Db"]["DeletionPolicy"] == policy
    modified["Resources"]["Db"]["DeletionPolicy"] = "Snapshot"
    assert modified == original == before


def test_unexpected_db_count_or_missing_choice_refuses():
    with pytest.raises(ValueError, match="exactly one"):
        snapshot_template({"Resources": {}}, "delete")
    with pytest.raises(ValueError, match="explicit"):
        snapshot_template({"Resources": {}}, "")


def test_unrelated_stack_refuses_before_template_update():
    class OtherStack:
        def describe_stacks(self, **kwargs):
            return {"Stacks": [{"Tags": [{"Key": "project", "Value": "someone-else"}]}]}

    with pytest.raises(ValueError, match="not tagged"):
        prepare_snapshot_policy(OtherStack(), "example", "this-project", "delete")


def test_policy_update_preserves_live_properties_and_parameters():
    class Stack:
        template = {"Resources": {"Db": {
            "Type": "AWS::RDS::DBInstance", "DeletionPolicy": "Snapshot",
            "Properties": {"Engine": "postgres", "DBInstanceClass": "existing-size"}}}}
        updated = None
        waited = False

        def describe_stacks(self, **kwargs):
            return {"Stacks": [{"Tags": [{"Key": "project", "Value": "this-project"}],
                                "StackStatus": "UPDATE_COMPLETE",
                                "Parameters": [{"ParameterKey": "ExistingParameter"}]}]}

        def get_template(self, **kwargs):
            return {"TemplateBody": self.template}

        def update_stack(self, **kwargs):
            self.updated = kwargs
            self.template = json.loads(kwargs["TemplateBody"])

        def get_waiter(self, name):
            assert name == "stack_update_complete"
            return self

        def wait(self, **kwargs):
            self.waited = True

    stack = Stack()
    prepare_snapshot_policy(stack, "example", "this-project", "delete")
    assert stack.waited
    assert stack.updated["Parameters"] == [{"ParameterKey": "ExistingParameter",
                                             "UsePreviousValue": True}]
    assert stack.template["Resources"]["Db"] == {
        "Type": "AWS::RDS::DBInstance", "DeletionPolicy": "Delete",
        "Properties": {"Engine": "postgres", "DBInstanceClass": "existing-size"}}


def test_default_dry_run_cannot_call_policy_update(monkeypatch):
    from scripts import teardown

    monkeypatch.setattr("sys.argv", ["teardown.py"])
    monkeypatch.setattr(teardown, "inventory", lambda *_: [])

    def forbidden(*_):
        raise AssertionError("dry run attempted a cloud write")

    monkeypatch.setattr(teardown, "prepare_snapshot_policy", forbidden)
    assert teardown.main() == 0
