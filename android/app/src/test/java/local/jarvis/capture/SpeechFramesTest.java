package local.jarvis.capture;

import org.junit.Test;
import static org.junit.Assert.*;
import java.io.*;

public class SpeechFramesTest {
    private byte[] stream(boolean finish) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        DataOutputStream out = new DataOutputStream(bytes);
        byte[] wav = new byte[44];
        System.arraycopy("RIFF".getBytes("US-ASCII"),0,wav,0,4);
        System.arraycopy("WAVE".getBytes("US-ASCII"),0,wav,8,4);
        out.writeInt(wav.length); out.write(wav);
        if (finish) out.writeInt(0);
        return bytes.toByteArray();
    }
    @Test public void firstFrameAvailableBeforeEndMarker() throws Exception {
        SpeechFrames frames = new SpeechFrames(new ByteArrayInputStream(stream(true)));
        assertEquals(44,frames.next().length);
        assertNull(frames.next());
    }
    @Test public void interruptedReplyIsNotSuccessful() throws Exception {
        SpeechFrames frames = new SpeechFrames(new ByteArrayInputStream(stream(false)));
        assertEquals(44,frames.next().length);
        assertThrows(EOFException.class,()->frames.next());
    }
    @Test public void malformedSizesAndEmptyStreamAreRejected() {
        for (int size : new int[]{0,-1,43,16000001}) {
            byte[] data = new byte[]{(byte)(size>>>24),(byte)(size>>>16),(byte)(size>>>8),(byte)size};
            SpeechFrames frames = new SpeechFrames(new ByteArrayInputStream(data));
            assertThrows(IOException.class,()->frames.next());
        }
    }
}
