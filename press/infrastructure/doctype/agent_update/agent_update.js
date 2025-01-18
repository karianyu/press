// Copyright (c) 2025, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Agent Update", {
    refresh(frm) {
        ["team", "cluster", "server_type", "server", "exclude_self_hosted"].forEach(field => {
            if (!frm.is_new()) {
                frm.set_df_property(field, "get_status", () => "Read");
            }
        });

        [
            [__('Start'), 'execute', frm.doc.status === 'Draft'],
            [__('Stop'), 'stop', frm.doc.status === 'Running'],
        ].forEach(([label, method, condition]) => {
            if (condition) {
                frm.add_custom_button(
                    label,
                    () => {
                        frappe.confirm(
                            `Are you sure you want to ${label.toLowerCase()}?`,
                            () => frm.call(method).then(() => frm.refresh()),
                        );
                    },
                    __('Actions'),
                );
            }
        });

        if (frm.doc.status !== 'Draft' && frm.doc.total > 0) {
            const progress_title = __('Agent Update Progress');
            let total = frm.doc.total;
            let progress = frm.doc.success + frm.doc.skipped + frm.doc.failure;
            frm.dashboard.show_progress(
                progress_title,
                (progress / total) * 100,
                `Agent Update Progress (${progress} servers completed out of ${total})`,
            );
        }
    },
});
