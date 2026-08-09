return {
  {
    "navarasu/onedark.nvim",
    priority = 1000,
    opts = {
      style = "dark",
      transparent = false,
      term_colors = true,
    },
  },
  {
    "LazyVim/LazyVim",
    opts = {
      colorscheme = "onedark",
    },
  },

  -- Session restoration is intentionally disabled: buffers and windows are
  -- useful here, but there is no project lifecycle to restore yet.
  { "folke/persistence.nvim", enabled = false },
}
