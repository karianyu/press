# Copyright (c) 2025, Frappe and contributors
# For license information, please see license.txt

# import frappe
from __future__ import annotations

from frappe.model.document import Document


class AgentUpdateServer(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF


		commit_hash: DF.Data | None
		git_show: DF.Code | None
		git_status: DF.Code | None
		has_uncommitted_files: DF.Check
		matched_commit_hash: DF.Check
		mismatched_upstream: DF.Check
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		play: DF.Link | None
		python_version: DF.Data | None
		server: DF.DynamicLink
		server_type: DF.Link
		status: DF.Literal["Pending", "Running", "Success", "Failure", "Skipped"]
		upstream: DF.Data | None
	# end: auto-generated types

	pass
