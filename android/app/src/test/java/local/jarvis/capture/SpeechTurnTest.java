package local.jarvis.capture;

import org.junit.Test;
import static org.junit.Assert.*;

public class SpeechTurnTest {
    @Test public void standaloneClosingPhrasesEndConversation() {
        assertTrue(SpeechTurn.isEndPhrase("That's all."));
        assertTrue(SpeechTurn.isEndPhrase("that is all"));
        assertTrue(SpeechTurn.isEndPhrase("End conversation!"));
        assertFalse(SpeechTurn.isEndPhrase("is that all on my calendar"));
        assertFalse(SpeechTurn.isEndPhrase("add goodbye party to my calendar"));
    }
    @Test public void wakeRequiresBothCompleteWords() {
        assertTrue(SpeechTurn.isWakePhrase("hey jarvis"));
        assertTrue(SpeechTurn.isWakePhrase("[unk] hey jarvis"));
        assertFalse(SpeechTurn.isWakePhrase("jarvis"));
        assertFalse(SpeechTurn.isWakePhrase("hey jarvison"));
        assertFalse(SpeechTurn.isWakePhrase("they jarvis"));
    }
    @Test public void hypothesesReplaceRatherThanDuplicate() {
        SpeechTurn turn = new SpeechTurn();
        turn.accept("what", false, 500);
        turn.accept("what did i", false, 500);
        turn.accept("what did i say today", true, 1000);
        assertFalse(turn.finished());
        turn.elapse(1500);
        assertTrue(turn.finished());
        assertEquals("what did i say today", turn.text());
    }
    @Test public void silenceTimesOutWithoutInventingQuestion() {
        SpeechTurn turn = new SpeechTurn();
        turn.accept("", true, 2000);
        assertFalse(turn.finished());
        turn.elapse(8000);
        assertTrue(turn.finished());
        assertEquals("", turn.text());
    }
    @Test public void uninterruptedSpeechHasHardLimit() {
        SpeechTurn turn = new SpeechTurn();
        turn.accept("what happened", false, 8000);
        assertFalse(turn.finished());
        turn.accept("what happened today", false, 12000);
        assertTrue(turn.finished());
        assertEquals("what happened today", turn.text());
    }
    @Test public void shortPauseDoesNotCutOffCalendarCommand() {
        SpeechTurn turn = new SpeechTurn();
        turn.accept("add dentist to my calendar", true, 3000);
        turn.accept("", false, 600);
        assertFalse(turn.finished());
        turn.accept("tomorrow", false, 200);
        turn.accept("tomorrow from three pm to four pm", true, 3000);
        turn.accept("", false, 1500);
        assertTrue(turn.finished());
        assertEquals("add dentist to my calendar tomorrow from three pm to four pm", turn.text());
    }
    @Test public void hardLimitKeepsCommittedAndCurrentPartial() {
        SpeechTurn turn = new SpeechTurn();
        turn.accept("move dentist", true, 8000);
        turn.accept("on my calendar tomorrow", false, 1000);
        turn.elapse(11000);
        assertTrue(turn.finished());
        assertEquals("move dentist on my calendar tomorrow", turn.text());
    }
}
