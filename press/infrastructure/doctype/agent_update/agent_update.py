# Copyright (c) 2025, Frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import time
from enum import Enum

import frappe
import requests
from frappe.model.document import Document

from press.press.doctype.app_source.app_source import get_timestamp_from_commit_info
from press.press.doctype.server.server import BaseServer
from press.press.report.server_stats.server_stats import get_servers


class AgentUpdate(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from press.infrastructure.doctype.agent_update_server.agent_update_server import AgentUpdateServer

		agent_repository_branch: DF.Data | None
		agent_repository_url: DF.Data | None
		cluster: DF.Link | None
		commit_author: DF.Data | None
		commit_hash: DF.Data | None
		commit_message: DF.Code | None
		commit_timestamp: DF.Datetime | None
		duration: DF.Duration | None
		end: DF.Datetime | None
		exclude_self_hosted: DF.Check
		name: DF.Int | None
		server: DF.Data | None
		server_type: DF.Link | None
		servers: DF.Table[AgentUpdateServer]
		start: DF.Datetime | None
		status: DF.Literal["Draft", "Pending", "Running", "Success", "Failure"]
		team: DF.Link | None
	# end: auto-generated types

	pass

	def before_insert(self):
		self.set_agent_repository()
		self.fetch_latest_commit()
		self.set_servers()

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

	def get_filters_dict(self):
		filters = frappe._dict()
		for field in ["team", "cluster", "server_type", "server_name", "exclude_self_hosted"]:
			if value := self.get(field):
				filters[field] = value
		return filters

	def set_servers(self):
		filters = self.get_filters_dict()
		for server in get_servers(filters):
			self.append(
				"servers", {"server_type": server.server_type, "status": "Pending", "server": server.name}
			)

	def _execute_update(self, server) -> UpdateStatus:
		return UpdateStatus.Success

	@frappe.whitelist()
	def execute_update(self, server_name):
		server = self.get_server(server_name)

		server.status = UpdateStatus.Running
		try:
			result = self._execute_update(server)
			server.status = result.name
			if result == UpdateStatus.Pending:
				# Wait some time before the next run
				time.sleep(1)
		except Exception:
			server.status = UpdateStatus.Failure

		if server.status == UpdateStatus.Failure:
			self.fail()
		else:
			self.next()

	@frappe.whitelist()
	def execute(self):
		self.status = Status.Running
		self.start = frappe.utils.now_datetime()
		self.save()
		self.next()

	def fail(self) -> None:
		self.status = Status.Failure
		for server in self.servers:
			if server.status == UpdateStatus.Pending:
				server.status = UpdateStatus.Skipped
		self.end = frappe.utils.now_datetime()
		self.duration = (self.end - self.start).total_seconds()
		self.save()

	def succeed(self) -> None:
		self.status = Status.Success
		self.end = frappe.utils.now_datetime()
		self.duration = (self.end - self.start).total_seconds()
		self.save()

	@frappe.whitelist()
	def next(self) -> None:
		self.status = Status.Running
		self.save()
		next_server = self.next_server

		if not next_server:
			# We've updated all servers
			self.succeed()
			return

		frappe.enqueue_doc(
			self.doctype,
			self.name,
			"execute_update",
			server_name=next_server.server,
			enqueue_after_commit=True,
		)

	@property
	def next_server(self) -> AgentUpdateServer | None:
		for server in self.servers:
			if server.status == UpdateStatus.Pending:
				return server
		return None

	def get_server(self, server_name) -> AgentUpdateServer | None:
		for server in self.servers:
			if server.server == server_name:
				return server
		return None


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


# TODO: Change (str, enum.Enum) to enum.StrEnum when migrating to Python 3.11
class UpdateStatus(str, Enum):
	Pending = "Pending"
	Running = "Running"
	Success = "Success"
	Failure = "Failure"
	Skipped = "Skipped"

	def __str__(self):
		return self.value


class Status(str, Enum):
	Draft = "Draft"
	Pending = "Pending"
	Running = "Running"
	Success = "Success"
	Failure = "Failure"

	def __str__(self):
		return self.value
