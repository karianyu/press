// Copyright (c) 2025, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Agent Update", {
    refresh(frm) {
        ["team", "cluster", "server_type", "server", "exclude_self_hosted"].forEach(field => {
            if (!frm.is_new()) {
                frm.set_df_property(field, "get_status", () => "Read");
            }
        });
    },
});
