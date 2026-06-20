#!/usr/bin/env ruby

require 'optparse'
require 'json'
require 'fileutils'
require 'net/http'
require 'uri'
require 'zlib'
require 'stringio'

STDOUT.sync = true

class ChatHistoryScanner
  DEFAULT_CHAT_LOGS_DIR = Dir.glob('C:/Users/danny/.runelite/chatlogs/*/clan')

  BROADCAST_PATTERNS = [
    # 1. Received collection log item
    /(.+?)\s+received a new collection log item:\s*(.+)/i,
    # 2. Received a drop
    /(.+?)\s+received a drop:\s*(.+)/i,
    # 3. Completed combat task
    /(.+?)\s+has completed a\s+(.+?)\s+combat task:\s*(.+)/i,
    /(.+?)\s+completed a\s+(.+?)\s+combat task:\s*(.+)/i,
    # 4. Completed quest
    /(.+?)\s+has completed a quest:\s*(.+)/i,
    /(.+?)\s+completed a quest:\s*(.+)/i,
    # 5. Reached XP in skill
    /(.+?)\s+has reached\s+([\d,]+)\s+XP in\s+(.+)/i,
    # 6. Defeated by someone/something
    /(.+?)\s+has been defeated by\s*(.+)/i,
    # 7. Completed event/minigame
    /(.+?)\s+has completed the\s*(.+)/i,
    /(.+?)\s+has completed\s*(.+)/i
  ]

  def initialize(options)
    raw_rsn = options[:rsn] || ""
    @rsn_list = raw_rsn.split(',').map(&:strip).reject(&:empty?)
    @chat_logs_dirs = options[:chat_logs_dirs] || DEFAULT_CHAT_LOGS_DIR

    # Load database name-change associations
    load_rsn_associations

    # Build targets and lookup maps
    @rsn_targets = {}              # maps normalized query RSN -> Array of normalized associated RSNs
    @scanned_rsn_to_query_rsn = {}  # maps normalized associated RSN -> normalized query RSN
    @rsn_data = {}                 # maps normalized query RSN -> scanner data

    @rsn_list.each do |rsn|
      norm_rsn = normalize_rsn(rsn)
      
      # Determine associated names (defaults to self if not found in DB)
      associated = if @rsn_association_map && @rsn_association_map.key?(norm_rsn)
                     @rsn_association_map[norm_rsn]
                   else
                     [rsn]
                   end
                   
      norm_associated = associated.map { |r| normalize_rsn(r) }
      @rsn_targets[norm_rsn] = norm_associated
      
      norm_associated.each do |norm_a|
        @scanned_rsn_to_query_rsn[norm_a] = norm_rsn
      end

      @rsn_data[norm_rsn] = {
        original_rsn: rsn,
        associated_rsns: associated, # Array of original name strings
        chats_count: 0,
        broadcasts_count: 0,
        last_chat_date: nil,
        last_broadcast_date: nil,
        chats: [],
        broadcasts: []
      }
    end

    @total_runelite_lines = 0
  end

  def run
    puts "=" * 60
    puts "CHAT HISTORY SCANNER STARTED"
    puts "Parameters:"
    puts "  RSNs: #{@rsn_list.join(', ')}"
    puts "=" * 60

    scan_runelite_logs

    if @rsn_list.length == 1
      generate_detailed_report(@rsn_list.first)
    else
      generate_csv_summary
    end

    print_console_summary
  end

  private

  # --- SUPABASE DATABASE LOOKUP ---

  def load_rsn_associations
    env_path = File.expand_path('../admin-bot/.env', __dir__)
    unless File.exist?(env_path)
      puts "Warning: .env file not found. Database RSN associations will not be loaded."
      return
    end

    url = nil
    key = nil
    File.readlines(env_path).each do |line|
      if line =~ /SUPABASE_URL\s*=\s*["']?([^"'\s]+)["']?/
        url = $1
      elsif line =~ /SUPABASE_KEY\s*=\s*["']?([^"'\s]+)["']?/
        key = $1
      end
    end

    if url.nil? || key.nil?
      puts "Warning: Supabase credentials missing in .env. Skipping database RSN associations."
      return
    end

    puts "Fetching name change associations from Supabase..."
    uri = URI("#{url}/rest/v1/member_rsns?select=member_id,rsn")
    request = Net::HTTP::Get.new(uri)
    request['apikey'] = key
    request['Authorization'] = "Bearer #{key}"

    response = Net::HTTP.start(uri.hostname, uri.port, use_ssl: true, read_timeout: 10) do |http|
      http.request(request)
    end

    unless response.code == '200'
      puts "Warning: Supabase API returned status #{response.code}. Skipping database associations."
      return
    end

    body = response.body
    if body && body[0..1] == "\x1F\x8B".force_encoding('BINARY')
      gz = Zlib::GzipReader.new(StringIO.new(body))
      body = gz.read
    end

    data = JSON.parse(body) rescue nil
    if data.nil? || !data.is_a?(Array)
      puts "Warning: Failed to parse Supabase JSON response."
      return
    end

    # Group RSNs by member_id
    member_groups = Hash.new { |h, k| h[k] = [] }
    data.each do |r|
      if r['member_id'] && r['rsn']
        member_groups[r['member_id']] << r['rsn']
      end
    end

    # Build association lookup map (normalized RSN -> list of all original associated RSNs)
    @rsn_association_map = {}
    member_groups.each do |_, rsns|
      rsns.each do |rsn|
        @rsn_association_map[normalize_rsn(rsn)] = rsns
      end
    end
    puts "Successfully loaded #{data.length} RSN records. Resolved #{member_groups.keys.length} clan members."
  rescue => e
    puts "Warning: Failed to load RSN associations: #{e.message}"
  end

  # --- RUNELITE SCANNING ---

  def scan_runelite_logs
    puts "\n--- Scanning RuneLite Chat Logs ---"
    
    # Filter only existing log directories
    existing_dirs = @chat_logs_dirs.select do |dir|
      exists = Dir.exist?(dir)
      puts "Warning: Directory #{dir} does not exist. Skipping." unless exists
      exists
    end

    if existing_dirs.empty?
      puts "No existing RuneLite log directories found."
      return
    end

    log_files = []
    existing_dirs.each do |dir|
      log_files.concat(Dir.glob(File.join(dir, "*.log")))
    end

    if log_files.empty?
      puts "No .log files found in directories."
      return
    end

    puts "Found #{log_files.length} log file(s) to scan."
    log_files.each do |file_path|
      scan_runelite_file(file_path)
    end
  end

  def scan_runelite_file(file_path)
    filename = File.basename(file_path)
    file_date = extract_date_from_filename(filename)

    # Read file with robust encoding handling
    begin
      content = File.read(file_path, mode: 'rb')
      content = content.force_encoding('UTF-8').scrub('?')
    rescue => e
      content = File.read(file_path, encoding: 'ISO-8859-1').encode('UTF-8', invalid: :replace, undef: :replace, replace: '?') rescue nil
    end

    return if content.nil?

    content.each_line do |line|
      line = line.strip
      next if line.empty?
      @total_runelite_lines += 1

      # Timestamp / image prefix filter
      next unless (match_data = line.match(/^(\d{2}:\d{2}:\d{2})\s*(?:<img=\d+>\s*)?(.+)$/))
      timestamp = match_data[1]
      rest = match_data[2].strip

      # Check if it is a broadcast
      if (broadcast_data = parse_broadcast(rest))
        player = broadcast_data[0]
        detail = broadcast_data[1]
        norm_player = normalize_rsn(player)

        if @scanned_rsn_to_query_rsn.key?(norm_player)
          query_rsn = @scanned_rsn_to_query_rsn[norm_player]
          data = @rsn_data[query_rsn]
          
          data[:broadcasts_count] += 1
          update_last_date(data, file_date, :broadcast)

          # Only collect message details if scanning a single query RSN
          if @rsn_list.length == 1
            data[:broadcasts] << {
              timestamp: timestamp,
              player: clean_display_name(player),
              detail: detail.strip,
              file: filename,
              date: file_date
            }
          end
        end

      # Check if it is a chat message
      elsif (chat_data = rest.match(/^\s*([^:]+?)\s*:\s*(.+)$/))
        sender = chat_data[1]
        message = chat_data[2]
        norm_sender = normalize_rsn(sender)

        if @scanned_rsn_to_query_rsn.key?(norm_sender)
          query_rsn = @scanned_rsn_to_query_rsn[norm_sender]
          data = @rsn_data[query_rsn]

          data[:chats_count] += 1
          update_last_date(data, file_date, :chat)

          # Only collect message details if scanning a single query RSN
          if @rsn_list.length == 1
            data[:chats] << {
              timestamp: timestamp,
              sender: clean_display_name(sender),
              message: message.strip,
              file: filename,
              date: file_date
            }
          end
        end
      end
    end
  end

  def parse_broadcast(text)
    BROADCAST_PATTERNS.each do |pattern|
      if match = text.match(pattern)
        player = match[1]
        # If the player name contains a colon that isn't part of a known prefix,
        # it is likely a chat message rather than a broadcast.
        if player.include?(':') && !player.match(/:\d+\|/)
          next
        end
        detail = match.captures[1..-1].compact.join(' ')
        return [player, detail]
      end
    end
    nil
  end

  def clean_display_name(name)
    return "" if name.nil?
    name = name.force_encoding('UTF-8').scrub(' ') rescue name.to_s
    name.gsub(/[\u00A0\u200B\s\?]+/, ' ').strip
  end

  def normalize_rsn(name)
    return "" if name.nil?
    name = name.force_encoding('UTF-8').scrub('?') rescue name.to_s
    name = name.gsub(/[\u00A0\u200B\s\?]+/, ' ')
    name = name.strip.downcase
    name = name.split('|').last.strip if name.include?('|')
    name
  end

  def extract_date_from_filename(filename)
    if match = filename.match(/(\d{4}-\d{2}-\d{2})/)
      match[1]
    else
      nil
    end
  end

  def update_last_date(data, date_str, type)
    return if date_str.nil?
    if type == :broadcast
      if data[:last_broadcast_date].nil? || date_str > data[:last_broadcast_date]
        data[:last_broadcast_date] = date_str
      end
    elsif type == :chat
      if data[:last_chat_date].nil? || date_str > data[:last_chat_date]
        data[:last_chat_date] = date_str
      end
    end
  end

  # --- REPORT GENERATION ---

  def generate_detailed_report(rsn)
    output_filename = "#{rsn}.txt"
    output_path = File.expand_path(output_filename, __dir__)

    norm_rsn = normalize_rsn(rsn)
    data = @rsn_data[norm_rsn]

    # Sort RuneLite messages
    sorted_chat = data[:chats].sort_by { |m| [m[:date] || "", m[:timestamp]] }
    sorted_broadcasts = data[:broadcasts].sort_by { |m| [m[:date] || "", m[:timestamp]] }

    File.open(output_path, 'w') do |f|
      f.puts "=" * 60
      f.puts "CHAT HISTORY SCAN REPORT"
      f.puts "Generated: #{Time.now}"
      f.puts "Query Parameters:"
      f.puts "  RSN: #{rsn}"
      f.puts "  Associated RSNs: #{data[:associated_rsns].join(', ')}" if data[:associated_rsns].length > 1
      f.puts "=" * 60
      f.puts

      f.puts "------------------------------------------------------------"
      f.puts "SUMMARY"
      f.puts "------------------------------------------------------------"
      f.puts "In-game Chat Messages Count: #{data[:chats_count]}"
      f.puts "Last In-game Chat Message Date: #{data[:last_chat_date] || 'N/A'}"
      f.puts "In-game Broadcasts Count: #{data[:broadcasts_count]}"
      f.puts "Last In-game Broadcast Date: #{data[:last_broadcast_date] || 'N/A'}"
      f.puts

      f.puts "------------------------------------------------------------"
      f.puts "IN-GAME CHAT MESSAGES"
      f.puts "------------------------------------------------------------"
      if sorted_chat.empty?
        f.puts "No in-game chat messages found."
      else
        sorted_chat.each do |msg|
          f.puts "[#{msg[:file]}] #{msg[:timestamp]} #{msg[:sender]}: #{msg[:message]}"
        end
      end
      f.puts

      f.puts "------------------------------------------------------------"
      f.puts "IN-GAME BROADCASTS"
      f.puts "------------------------------------------------------------"
      if sorted_broadcasts.empty?
        f.puts "No in-game broadcasts found."
      else
        sorted_broadcasts.each do |msg|
          f.puts "[#{msg[:file]}] #{msg[:timestamp]} #{msg[:player]} #{msg[:detail]}"
        end
      end
      f.puts
    end

    puts "\nDetailed report written to: #{output_path}"
  end

  def generate_csv_summary
    output_filename = "chat_history_summary.csv"
    output_path = File.expand_path(output_filename, __dir__)

    File.open(output_path, 'w') do |f|
      f.puts "rsn,broadcasts,last_broadcast_date,chats,last_chat_date"
      
      # Retain original order of input RSNs
      @rsn_list.each do |rsn|
        norm_rsn = normalize_rsn(rsn)
        data = @rsn_data[norm_rsn]
        
        last_b_date = data[:last_broadcast_date] || ""
        last_c_date = data[:last_chat_date] || ""
        
        # Quote names if they contain commas
        display_name = rsn.include?(',') ? "\"#{rsn}\"" : rsn

        f.puts "#{display_name},#{data[:broadcasts_count]},#{last_b_date},#{data[:chats_count]},#{last_c_date}"
      end
    end

    puts "\nSummary CSV written to: #{output_path}"
  end

  def print_console_summary
    puts "\n" + "=" * 60
    puts "SCAN SUMMARY"
    puts "=" * 60
    @rsn_list.each do |rsn|
      norm_rsn = normalize_rsn(rsn)
      data = @rsn_data[norm_rsn]
      puts "RSN: #{rsn}"
      puts "  - Associated Names: #{data[:associated_rsns].join(', ')}" if data[:associated_rsns].length > 1
      puts "  - Chat Messages: #{data[:chats_count]} (Last: #{data[:last_chat_date] || 'N/A'})"
      puts "  - Broadcasts:    #{data[:broadcasts_count]} (Last: #{data[:last_broadcast_date] || 'N/A'})"
      puts "-" * 40 if @rsn_list.length > 1
    end
    puts "=" * 60
  end
end

if __FILE__ == $0
  options = {}
  parser = OptionParser.new do |opts|
    opts.banner = "Usage: ruby chat-history.rb [options]"

    opts.on("--rsn RSN_LIST", String, "Comma-separated list of RuneScape Names to scan") do |v|
      options[:rsn] = v
    end
  end

  begin
    parser.parse!
  rescue OptionParser::InvalidOption, OptionParser::MissingArgument => e
    puts e.message
    puts parser
    exit 1
  end

  if options[:rsn].nil?
    puts "Error: You must provide the --rsn argument with a list of RSNs"
    puts parser
    exit 1
  end

  scanner = ChatHistoryScanner.new(options)
  scanner.run
end
