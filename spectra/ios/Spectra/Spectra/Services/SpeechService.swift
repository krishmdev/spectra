import Foundation
import Speech
import AVFoundation

final class SpeechService: ObservableObject {
    @Published var isListening = false
    @Published var transcript = ""
    @Published var errorMessage: String?

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private var recognitionTask: SFSpeechRecognitionTask?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private let audioEngine = AVAudioEngine()
    private var silenceTimer: Timer?
    private let silenceTimeout: TimeInterval = 3.0

    func startListening() {
        guard !isListening else { return }
        errorMessage = nil

        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            DispatchQueue.main.async {
                switch status {
                case .authorized:
                    self?.checkMicrophoneAndBegin()
                case .denied, .restricted:
                    self?.errorMessage = "Speech recognition not authorized. Enable in Settings > Privacy."
                case .notDetermined:
                    self?.errorMessage = "Speech permission not yet granted."
                @unknown default:
                    self?.errorMessage = "Speech recognition unavailable."
                }
            }
        }
    }

    func stopListening() {
        silenceTimer?.invalidate()
        silenceTimer = nil
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionTask?.cancel()
        recognitionTask = nil
        request?.endAudio()
        request = nil
        DispatchQueue.main.async {
            self.isListening = false
        }
    }

    private func checkMicrophoneAndBegin() {
        AVAudioApplication.requestRecordPermission { [weak self] granted in
            DispatchQueue.main.async {
                if granted {
                    self?.beginRecognition()
                } else {
                    self?.errorMessage = "Microphone access denied. Enable in Settings > Privacy."
                }
            }
        }
    }

    private func beginRecognition() {
        guard let recognizer = recognizer, recognizer.isAvailable else {
            errorMessage = "Speech recognizer not available on this device."
            return
        }

        let audioSession = AVAudioSession.sharedInstance()
        do {
            try audioSession.setCategory(.record, mode: .measurement, options: .duckOthers)
            try audioSession.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            errorMessage = "Audio session error: \(error.localizedDescription)"
            return
        }

        request = SFSpeechAudioBufferRecognitionRequest()
        guard let request = request else {
            errorMessage = "Could not create speech request."
            return
        }
        request.shouldReportPartialResults = true

        let inputNode = audioEngine.inputNode
        let recordingFormat = inputNode.outputFormat(forBus: 0)

        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { buffer, _ in
            request.append(buffer)
        }

        do {
            try audioEngine.start()
        } catch {
            errorMessage = "Audio engine error: \(error.localizedDescription)"
            return
        }

        isListening = true
        transcript = ""
        resetSilenceTimer()

        recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self = self else { return }

            if let result = result {
                DispatchQueue.main.async {
                    self.transcript = result.bestTranscription.formattedString
                    self.resetSilenceTimer()
                }

                if result.isFinal {
                    self.stopListening()
                }
            }

            if let error = error {
                DispatchQueue.main.async {
                    self.errorMessage = "Recognition error: \(error.localizedDescription)"
                }
                self.stopListening()
            }
        }
    }

    private func resetSilenceTimer() {
        silenceTimer?.invalidate()
        silenceTimer = Timer.scheduledTimer(withTimeInterval: silenceTimeout, repeats: false) { [weak self] _ in
            self?.stopListening()
        }
    }
}
