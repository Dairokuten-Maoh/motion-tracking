package local.jarvis.capture;

import java.io.DataInputStream;
import java.io.IOException;
import java.io.InputStream;

/** Bounded WAV frames: big-endian length followed by bytes; zero is required EOF.
 * Unexpected EOF is a failed reply, never a successful partial playback. */
final class SpeechFrames {
    private final DataInputStream input;
    private int total, count;
    SpeechFrames(InputStream input) { this.input = new DataInputStream(input); }
    byte[] next() throws IOException {
        int length = input.readInt();
        if (length == 0) {
            if (count == 0) throw new IOException("Empty speech stream");
            return null;
        }
        if (length < 44 || length > 16000000 - total || ++count > 128)
            throw new IOException("Invalid speech frame size");
        byte[] wav = new byte[length];
        input.readFully(wav);
        if (wav[0]!='R' || wav[1]!='I' || wav[2]!='F' || wav[3]!='F'
                || wav[8]!='W' || wav[9]!='A' || wav[10]!='V' || wav[11]!='E')
            throw new IOException("Invalid speech frame format");
        total += length;
        return wav;
    }
}
