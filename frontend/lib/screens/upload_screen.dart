/// Upload screen — pick audio, MIDI, or type a song title, then submit a job.
library;

import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../api/client.dart';
import '../api/models.dart';
import 'progress_screen.dart';

enum _SourceMode { audio, midi, title }

class UploadScreen extends StatefulWidget {
  const UploadScreen({super.key, required this.api});
  final OhSheetApi api;

  @override
  State<UploadScreen> createState() => _UploadScreenState();
}

class _UploadScreenState extends State<UploadScreen> {
  _SourceMode _mode = _SourceMode.audio;
  final _titleController = TextEditingController();
  final _artistController = TextEditingController();

  PlatformFile? _pickedFile;
  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _titleController.dispose();
    _artistController.dispose();
    super.dispose();
  }

  Future<void> _pick() async {
    final isAudio = _mode == _SourceMode.audio;
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: isAudio
          ? const ['mp3', 'wav', 'flac', 'm4a']
          : const ['mid', 'midi'],
      withData: true, // ensures bytes are populated on web
    );
    if (result == null || result.files.isEmpty) return;
    setState(() {
      _pickedFile = result.files.first;
      _error = null;
    });
  }

  Future<void> _submit() async {
    setState(() {
      _submitting = true;
      _error = null;
    });

    try {
      JobSummary job;
      switch (_mode) {
        case _SourceMode.audio:
          if (_pickedFile == null) throw StateError('Pick an audio file first');
          final bytes = _pickedFile!.bytes;
          if (bytes == null) throw StateError('File bytes unavailable on this platform');
          final audio = await widget.api.uploadAudio(
            bytes: Uint8List.fromList(bytes),
            filename: _pickedFile!.name,
          );
          job = await widget.api.createJob(
            audio: audio,
            title: _titleController.text.trim().isEmpty
                ? null
                : _titleController.text.trim(),
            artist: _artistController.text.trim().isEmpty
                ? null
                : _artistController.text.trim(),
          );
          break;
        case _SourceMode.midi:
          if (_pickedFile == null) throw StateError('Pick a MIDI file first');
          final bytes = _pickedFile!.bytes;
          if (bytes == null) throw StateError('File bytes unavailable on this platform');
          final midi = await widget.api.uploadMidi(
            bytes: Uint8List.fromList(bytes),
            filename: _pickedFile!.name,
          );
          job = await widget.api.createJob(
            midi: midi,
            title: _titleController.text.trim().isEmpty
                ? null
                : _titleController.text.trim(),
            artist: _artistController.text.trim().isEmpty
                ? null
                : _artistController.text.trim(),
          );
          break;
        case _SourceMode.title:
          final title = _titleController.text.trim();
          if (title.isEmpty) throw StateError('Enter a song title');
          job = await widget.api.createJob(
            title: title,
            artist: _artistController.text.trim().isEmpty
                ? null
                : _artistController.text.trim(),
          );
          break;
      }

      if (!mounted) return;
      await Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => ProgressScreen(api: widget.api, jobId: job.jobId),
        ),
      );
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final needsFile = _mode != _SourceMode.title;
    final canSubmit = !_submitting &&
        (_mode == _SourceMode.title
            ? _titleController.text.trim().isNotEmpty
            : _pickedFile != null);

    return Scaffold(
      appBar: AppBar(title: const Text('Oh Sheet')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SegmentedButton<_SourceMode>(
              segments: const [
                ButtonSegment(value: _SourceMode.audio, label: Text('Audio')),
                ButtonSegment(value: _SourceMode.midi, label: Text('MIDI')),
                ButtonSegment(value: _SourceMode.title, label: Text('Title')),
              ],
              selected: {_mode},
              onSelectionChanged: (s) => setState(() {
                _mode = s.first;
                _pickedFile = null;
                _error = null;
              }),
            ),
            const SizedBox(height: 24),
            if (needsFile) ...[
              OutlinedButton.icon(
                onPressed: _submitting ? null : _pick,
                icon: const Icon(Icons.attach_file),
                label: Text(
                  _pickedFile == null
                      ? (_mode == _SourceMode.audio
                          ? 'Pick audio file (mp3/wav/flac/m4a)'
                          : 'Pick MIDI file (.mid/.midi)')
                      : _pickedFile!.name,
                ),
              ),
              const SizedBox(height: 16),
            ],
            TextField(
              controller: _titleController,
              decoration: InputDecoration(
                labelText: _mode == _SourceMode.title
                    ? 'Song title (required)'
                    : 'Title (optional)',
                border: const OutlineInputBorder(),
              ),
              onChanged: (_) => setState(() {}),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _artistController,
              decoration: const InputDecoration(
                labelText: 'Artist (optional)',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 24),
            FilledButton.icon(
              onPressed: canSubmit ? _submit : null,
              icon: _submitting
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.play_arrow),
              label: Text(_submitting ? 'Submitting…' : 'Transcribe'),
            ),
            if (_error != null) ...[
              const SizedBox(height: 16),
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
