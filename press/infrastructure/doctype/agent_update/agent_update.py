# Copyright (c) 2025, Frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import time
from collections import defaultdict
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
		failure: DF.Int
		ignore_failures: DF.Check
		name: DF.Int | None
		pending: DF.Int
		running: DF.Int
		server: DF.Data | None
		server_type: DF.Link | None
		servers: DF.Table[AgentUpdateServer]
		skipped: DF.Int
		start: DF.Datetime | None
		status: DF.Literal["Draft", "Ready", "Running", "Success", "Failure"]
		success: DF.Int
		team: DF.Link | None
		total: DF.Int
	# end: auto-generated types

	pass

	def before_insert(self):
		self.set_agent_repository()
		self.fetch_latest_commit()
		self.set_servers()

	def after_insert(self):
		self.prepare()

	def before_save(self):
		self.update_statistics()

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
				"servers",
				{"server_type": server.server_type, "status": UpdateStatus.Pending, "server": server.name},
			)

	def _create_play(self, server):
		# Ansible Play will be created in the background. It might not be created immediately
		# update_agent_ansible is deduplicated, so we can call it multiple times (iff we don't have a play)
		frappe.get_doc(server.server_type, server.server).update_agent_ansible()

	def _find_play(self, server):
		plays = frappe.get_all(
			"Ansible Play",
			{"server": server.server, "play": "Update Agent", "creation": (">", self.creation)},
			pluck="name",
			order_by="creation desc",
			limit=1,
		)
		if plays:
			return plays[0]
		return None

	def _get_status_based_on_play(self, play):
		play_status = frappe.db.get_value("Ansible Play", play, "status")
		if play_status == "Pending":
			play_status = "Running"
		return UpdateStatus(play_status)

	def _execute_update(self, server) -> UpdateStatus:
		if server.status == UpdateStatus.Pending:
			# Update hasn't started for this serer yet
			# Create a play and return immediately (do not wait for the play).
			# Look for it in the next run
			self._create_play(server)
			return UpdateStatus.Running

		if server.status == UpdateStatus.Running:
			if not server.play:
				# Look for the play we created in the previous run
				server.play = self._find_play(server)

			if server.play:
				# Play is created. Check status
				return self._get_status_based_on_play(server.play)

			# Play isn't created yet. Try again in the next run
			return UpdateStatus.Running

		# Nothing to do for Success or Failure
		return UpdateStatus(server.status)

	@frappe.whitelist()
	def execute_update(self, server_name):
		server = self.get_server(server_name)
		try:
			server.status = self._execute_update(server)
		except Exception:
			server.status = UpdateStatus.Failure

		if server.status in (UpdateStatus.Pending, UpdateStatus.Running):
			# Wait some time before the next run
			time.sleep(1)

		if (server.status == UpdateStatus.Failure) and (not self.ignore_failures):
			# Stop the update iff we're not ignoring failures
			self.fail()
		else:
			self.next()

	@frappe.whitelist()
	def execute(self):
		self.status = Status.Running
		self.start = frappe.utils.now_datetime()
		self.save()
		self.next()

	@frappe.whitelist()
	def stop(self):
		self.fail()

	def fail(self) -> None:
		self.status = Status.Failure
		for server in self.servers:
			if server.status == UpdateStatus.Pending:
				server.status = UpdateStatus.Skipped
		self.end = frappe.utils.now_datetime()
		start = frappe.utils.get_datetime(self.start)
		self.duration = (self.end - start).total_seconds()
		self.save()

	def succeed(self) -> None:
		self.status = Status.Success
		self.end = frappe.utils.now_datetime()
		start = frappe.utils.get_datetime(self.start)
		self.duration = (self.end - start).total_seconds()
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
			if server.status in (UpdateStatus.Pending, UpdateStatus.Running):
				return server
		return None

	def get_server(self, server_name) -> AgentUpdateServer | None:
		for server in self.servers:
			if server.server == server_name:
				return server
		return None

	def update_statistics(self):
		counts = defaultdict(int)
		for server in self.servers:
			counts[server.status] = counts.get(server.status, 0) + 1
		for status in UpdateStatus:
			self.set(status.lower(), counts[status])
		self.total = sum(counts.values())

	@frappe.whitelist()
	def prepare(self):
		frappe.enqueue_doc(
			self.doctype,
			self.name,
			"_prepare",
			enqueue_after_commit=True,
			deduplicate=True,
			job_id=f"prepare_agent_update:{self.name}",
			queue="long",
			timeout=3600,  # Fetching Agent versions can take a long time
		)

	def _prepare(self):
		self.set_agent_versions()
		self.skip_updates_with_known_issues()
		self.status = Status.Ready
		self.save()

	def skip_updates_with_known_issues(self):
		for server in self.servers:
			if server.upstream and server.upstream != self.agent_repository_url:
				server.mismatched_upstream = True
			if server.commit_hash and server.commit_hash == self.commit_hash:
				server.matched_commit_hash = True
			if server.git_status:
				server.has_uncommitted_files = True

			if server.mismatched_upstream or server.matched_commit_hash or server.has_uncommitted_files:
				server.status = UpdateStatus.Skipped

	def set_agent_versions(self):
		for server in self.servers:
			if server.upstream:
				# We already have the version information for this server
				continue

			version = frappe.get_cached_doc(server.server_type, server.server).get_agent_version()

			if version:
				# We use this to skip updates with known issues
				server.upstream = version.get("upstream", "").strip()
				server.commit_hash = version.get("commit", "").strip()
				server.git_status = version.get("status", "").strip()

				server.git_show = version.get("show")
				server.python_version = version.get("python")

				self.save(ignore_version=True)
				frappe.db.commit()


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
	Ready = "Ready"
	Running = "Running"
	Success = "Success"
	Failure = "Failure"

	def __str__(self):
		return self.value
