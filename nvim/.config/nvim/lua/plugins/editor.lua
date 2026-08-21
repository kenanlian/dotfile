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

  -- Keep cursor jumps immediate instead of animating them as smooth scrolls.
  {
    "folke/snacks.nvim",
    opts = {
      scroll = { enabled = false },
    },
  },

  -- Session restoration is intentionally disabled: buffers and windows are
  -- useful here, but there is no project lifecycle to restore yet.
  { "folke/persistence.nvim", enabled = false },
}
