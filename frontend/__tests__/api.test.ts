import { uploadMidi, uploadAudio, submitJob, listJobs, getJob } from "../lib/api";

const mockFetch = jest.fn();
global.fetch = mockFetch;

beforeEach(() => {
  mockFetch.mockReset();
});

describe("API client", () => {
  describe("uploadMidi", () => {
    it("POSTs file to /v1/uploads/midi and returns remote ref", async () => {
      const midiRef = {
        uri: "file://blob/uploads/midi/abc123.mid",
        ticks_per_beat: 480,
        content_hash: "abc123",
      };
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(midiRef),
      });

      const file = new File(["midi-data"], "test.mid", { type: "audio/midi" });
      const result = await uploadMidi(file);

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const [url, opts] = mockFetch.mock.calls[0];
      expect(url).toBe("http://localhost:8000/v1/uploads/midi");
      expect(opts.method).toBe("POST");
      expect(opts.body).toBeInstanceOf(FormData);
      expect(result).toEqual(midiRef);
    });

    it("throws on non-OK response", async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 415,
        json: () => Promise.resolve({ detail: "Unsupported format" }),
      });

      const file = new File(["data"], "bad.txt", { type: "text/plain" });
      await expect(uploadMidi(file)).rejects.toThrow();
    });
  });

  describe("uploadAudio", () => {
    it("POSTs file to /v1/uploads/audio and returns remote ref", async () => {
      const audioRef = {
        uri: "file://blob/uploads/audio/def456.mp3",
        format: "mp3",
        sample_rate: 44100,
        duration_sec: 180.5,
        channels: 2,
        content_hash: "def456",
      };
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(audioRef),
      });

      const file = new File(["audio-data"], "song.mp3", { type: "audio/mpeg" });
      const result = await uploadAudio(file);

      const [url, opts] = mockFetch.mock.calls[0];
      expect(url).toBe("http://localhost:8000/v1/uploads/audio");
      expect(opts.method).toBe("POST");
      expect(result.format).toBe("mp3");
    });
  });

  describe("submitJob", () => {
    it("POSTs job with MIDI reference and returns job summary", async () => {
      const jobSummary = {
        job_id: "job-123",
        status: "pending",
        variant: "midi_upload",
        title: "Test Song",
        artist: null,
        error: null,
        result: null,
      };
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(jobSummary),
      });

      const midiRef = { uri: "file://blob/test.mid", ticks_per_beat: 480, content_hash: "abc" };
      const result = await submitJob({ midi: midiRef, title: "Test Song" });

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const [url, opts] = mockFetch.mock.calls[0];
      expect(url).toBe("http://localhost:8000/v1/jobs");
      expect(opts.method).toBe("POST");
      expect(JSON.parse(opts.body)).toMatchObject({ midi: midiRef, title: "Test Song" });
      expect(result.job_id).toBe("job-123");
    });
  });

  describe("listJobs", () => {
    it("GETs /v1/jobs and returns array", async () => {
      const jobs = [{ job_id: "j1", status: "succeeded", title: "Song A" }];
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(jobs),
      });

      const result = await listJobs();

      expect(mockFetch).toHaveBeenCalledWith("http://localhost:8000/v1/jobs");
      expect(result).toHaveLength(1);
      expect(result[0].job_id).toBe("j1");
    });
  });

  describe("getJob", () => {
    it("GETs /v1/jobs/:id and returns job details", async () => {
      const job = { job_id: "j1", status: "succeeded", result: { pdf_uri: "file://test.pdf" } };
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(job),
      });

      const result = await getJob("j1");

      expect(mockFetch).toHaveBeenCalledWith("http://localhost:8000/v1/jobs/j1");
      expect(result.job_id).toBe("j1");
    });

    it("throws on 404", async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 404,
        json: () => Promise.resolve({ detail: "not found" }),
      });

      await expect(getJob("nonexistent")).rejects.toThrow();
    });
  });
});
