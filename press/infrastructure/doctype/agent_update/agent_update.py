# Copyright (c) 2025, Frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
import requests
from frappe.model.document import Document

from press.press.doctype.app_source.app_source import get_timestamp_from_commit_info
from press.press.doctype.server.server import BaseServer


class AgentUpdate(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		agent_repository_branch: DF.Data | None
		agent_repository_url: DF.Data | None
		commit_author: DF.Data | None
		commit_hash: DF.Data | None
		commit_message: DF.Code | None
		commit_timestamp: DF.Datetime | None
		name: DF.Int | None
	# end: auto-generated types

	pass

	def before_insert(self):
		self.set_agent_repository()
		self.fetch_latest_commit()

	def set_agent_repository(self):
		self.agent_repository_url = BaseServer.get_agent_repository_url().removesuffix(".git")
		self.agent_repository_branch = BaseServer.get_agent_repository_branch()

	def fetch_latest_commit(self):
		# Assumes repository_url looks like https://github.com/frappe/agent
		_, owner, repository = self.agent_repository_url.rsplit("/", 2)

		branch = GitHubBranch(owner, repository, self.agent_repository_branch)
		commit = branch.commit

		self.commit_hash = commit.hash
		self.commit_message = commit.message
		self.commit_author = commit.author
		self.commit_timestamp = commit.timestamp


class GitHubCommit:
	hash: str
	message: str
	author: str
	timestamp: str

	def __init__(self, data):
		self.hash = data.sha

		self.message = data.commit["message"]
		self.author = data.commit["author"]["name"]
		self.timestamp = get_timestamp_from_commit_info(data.commit)


class GitHubBranch:
	commit: GitHubCommit

	def __init__(self, owner, repository, branch):
		self.url = f"https://api.github.com/repos/{owner}/{repository}/branches/{branch}"
		data = requests.get(self.url).json()
		self.commit = GitHubCommit(frappe._dict(data["commit"]))
