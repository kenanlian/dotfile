-- Treat the shell's working directory as the editing scope. This keeps file
-- pickers useful for ad-hoc files without introducing project-root behavior.
vim.g.root_spec = { "cwd" }

local opt = vim.opt

opt.scrolloff = 6
opt.sidescrolloff = 8
opt.wrap = false
