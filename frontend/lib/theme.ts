/** Where the header toggle stores an explicit light/dark choice. */
export const THEME_KEY = "tomo-theme";

/**
 * Applied in <head> before first paint so a saved theme never flashes. Without a saved choice
 * the stylesheet follows the system's prefers-color-scheme.
 */
export const THEME_SCRIPT = `try{var t=localStorage.getItem("${THEME_KEY}");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;
