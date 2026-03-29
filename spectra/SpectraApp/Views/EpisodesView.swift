import SwiftUI

struct EpisodeModel: Identifiable, Codable {
    let id: String
    let task_description: String
    let step_count: Int
    let occurrence_count: Int
    let app_bundle_id: String
    let created_at: TimeInterval
}

/* 
 Note: Requires WebSocketStore or similar store object to pass the WebSocket
 array of episodes (`store.episodes`) and the replay/delete requests methods.
*/
struct EpisodesView: View {
    @ObservedObject var store: WebSocketStore // Ensure your WebSocketStore matches this interface
    
    var body: some View {
        NavigationView {
            List {
                ForEach(store.episodes) { episode in
                    VStack(alignment: .leading, spacing: 6) {
                        Text(episode.task_description)
                            .font(.headline)
                        
                        HStack {
                            Text("\(episode.step_count) steps")
                            Text("•")
                            Text("Run \(episode.occurrence_count) times")
                            Text("•")
                            Text(episode.app_bundle_id.split(separator: ".").last ?? "")
                        }
                        .font(.caption)
                        .foregroundColor(.secondary)
                        
                        Text(formatDate(episode.created_at))
                            .font(.caption2)
                            .foregroundColor(.gray)
                        
                        Button(action: {
                            store.sendReplayRequest(episodeId: episode.id)
                        }) {
                            Text("Run now")
                                .font(.subheadline)
                                .fontWeight(.medium)
                                .foregroundColor(.white)
                                .padding(.vertical, 6)
                                .padding(.horizontal, 12)
                                .background(Color.accentColor)
                                .cornerRadius(8)
                        }
                        .padding(.top, 4)
                        .buttonStyle(PlainButtonStyle())
                    }
                    .padding(.vertical, 4)
                }
                .onDelete { indexSet in
                    for index in indexSet {
                        let episode = store.episodes[index]
                        store.sendDeleteEpisode(episodeId: episode.id)
                        store.episodes.remove(at: index)
                    }
                }
            }
            .navigationTitle("History")
            .onAppear {
                store.requestEpisodes()
            }
        }
    }
    
    private func formatDate(_ timestamp: TimeInterval) -> String {
        let date = Date(timeIntervalSince1970: timestamp)
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .full
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}
