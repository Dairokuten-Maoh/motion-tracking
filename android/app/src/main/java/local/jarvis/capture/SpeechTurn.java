package local.jarvis.capture;

/** Joins finalized recognition segments across short pauses, replacing partial hypotheses.
 * Allow 1.5 seconds after a recognizer endpoint before submitting, up to 20 seconds total. */
final class SpeechTurn {
    private String committed = "", partial = "";
    private int elapsed;
    private int quiet = -1;

    static boolean isWakePhrase(String words) {
        return (" " + words.trim().toLowerCase(java.util.Locale.ROOT) + " ").contains(" hey jarvis ");
    }
    /** Only a complete standalone closing phrase ends the exchange; never a substring. */
    static boolean isEndPhrase(String words) {
        String normalized = words.toLowerCase(java.util.Locale.ROOT).replaceAll("['’.,!?]", "").trim().replaceAll("\\s+", " ");
        return normalized.equals("thats all") || normalized.equals("that is all")
            || normalized.equals("end conversation") || normalized.equals("stop talking")
            || normalized.equals("goodbye") || normalized.equals("thanks thats all");
    }
    void accept(String words, boolean finalResult, int milliseconds) {
        elapse(milliseconds);
        words = words.trim();
        if (finalResult) {
            if (!words.isEmpty()) {
                committed = (committed + " " + words).trim();
                quiet = 0;
            }
            partial = "";
            if (!committed.isEmpty() && quiet < 0) quiet = 0;
        } else if (!words.isEmpty()) {
            partial = words;
            quiet = -1;
        }
    }
    void elapse(int milliseconds) { elapsed += milliseconds; if (quiet >= 0) quiet += milliseconds; }
    boolean finished() { return quiet >= 1500 || elapsed >= (text().isEmpty() ? 10000 : 20000); }
    String text() { return (committed + " " + partial).trim(); }
}
