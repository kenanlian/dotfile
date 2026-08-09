-- LazyVim already provides buffer, window, explorer, and search mappings.
-- These two overrides make the common pickers explicitly use the current
-- working directory, which is friendlier for unrelated files.
vim.keymap.set("n", "<leader>ff", LazyVim.pick("files", { root = false }), { desc = "Find Files (cwd)" })
vim.keymap.set("n", "<leader>sg", LazyVim.pick("live_grep", { root = false }), { desc = "Grep (cwd)" })

vim.keymap.set("n", "<leader>fn", "<cmd>enew<cr>", { desc = "New File" })
vim.keymap.set({ "n", "i", "x" }, "<D-s>", "<cmd>write<cr>", { desc = "Save File" })
