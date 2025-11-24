#!/usr/bin/env ruby

require 'fileutils'

class RuneLiteChatScanner
  def initialize(username, chat_logs_dir = ['C:/Users/danny/.runelite/chatlogs/CorvusUmbra/clan', 'C:/Users/danny/.runelite/chatlogs/Corvidastir/clan', 'C:/Users/danny/.runelite/chatlogs/CorvidsNest/clan'])
    @username = username.downcase # Case insensitive matching
    @chat_logs_dir = chat_logs_dir
    @total_messages = 0
    @user_messages = []
    @user_message_count = 0
  end

  def scan_logs
    puts "Scanning chat logs for username: #{@username}"
    puts "Directories: #{@chat_logs_dir.join(', ')}"
    puts "-" * 50

    @chat_logs_dir.each do |dir|
      unless Dir.exist?(dir)
        puts "Error: Directory #{dir} does not exist!"
        return
      end
    end

    log_files = []
    @chat_logs_dir.each do |dir|
      log_files.concat(Dir.glob(File.join(dir, "*.log")))
    end

    if log_files.empty?
      puts "No .log files found in any of the directories"
      return
    end

    puts "Found #{log_files.length} log file(s) to scan..."
    puts "=" * 50
    log_files.each do |file_path|
      scan_file(file_path)
    end

    generate_output
    print_summary
  end

  private

  def scan_file(file_path)
    filename = File.basename(file_path)
    puts "Scanning #{filename}..."
    
    file_message_count = 0
    file_user_messages = 0

    # Read file with robust encoding handling
    begin
      content = File.read(file_path, mode: 'rb')
      content = content.force_encoding('UTF-8').scrub('?')
    rescue => encoding_error
      puts "  - Encoding error, trying alternative approach: #{encoding_error.message}"
      content = File.read(file_path, encoding: 'ISO-8859-1').encode('UTF-8', invalid: :replace, undef: :replace, replace: '?')
    end
    
    content.each_line do |line|
      line = line.strip
      next if line.empty?
      
      # 1. System Message Filter (P1)
      # Rely on the colon (:) to identify potential user chat lines.
      match_data = line.match(/^(\d{2}:\d{2}:\d{2})\s*(?:<img=\d+>\s*)?([^:]+?)\s*:\s*(.+)$/)

      if match_data
        
        username_raw  = match_data[2]
        message_raw   = match_data[3]
        
        # --- System Message Heuristic Filter Maintained ---
        system_phrases = [" received ", " completed ", " has reached "]
        lower_message = message_raw.downcase
        next if system_phrases.any? { |phrase| lower_message.include?(phrase) }
        
        # --- ASCII '?' Cleansing (P2 FIX) ---
        
        # The debug output shows the character is a literal ASCII '?'. 
        # Replace the literal '?' with a standard space (' ').
        username = username_raw.gsub('?', ' ').strip
        
        # This converts "Grey Bags" to "Grey Bags" (with a standard space)
        # and "I See Uranus" to "I See Uranus" (with standard spaces).

        # --- Final Processing and Comparison ---

        @total_messages += 1
        file_message_count += 1
        
        message = message_raw.strip
        timestamp = match_data[1]
        
        # The comparison should now succeed.
        if username.downcase == @username.downcase 
          @user_messages << {
            timestamp: timestamp,
            username: username,
            message: message,
            file: filename
          }
          @user_message_count += 1
          file_user_messages += 1
        end
      end
    end
    
    puts "  - #{file_message_count} total messages, #{file_user_messages} from #{@username}"
  rescue => e
    puts "Error reading #{file_path}: #{e.message}"
  end

  def generate_output
    output_filename = "#{@username}.txt"
    
    File.open(output_filename, 'w') do |file|
      file.puts "Chat Messages for User: #{@username}"
      file.puts "Generated: #{Time.now}"
      file.puts "Total messages found: #{@user_message_count}"
      file.puts "=" * 60
      file.puts

      @user_messages.each do |msg|
        file.puts "[#{msg[:file]}] #{msg[:timestamp]} #{msg[:username]}: #{msg[:message]}"
      end
    end
    
    puts "\nOutput written to: #{output_filename}"
  end

  def print_summary
    puts "\n" + "=" * 50
    puts "SCAN SUMMARY"
    puts "=" * 50
    puts "Username searched: #{@username}"
    puts "Total messages scanned: #{@total_messages}"
    puts "Messages from #{@username}: #{@user_message_count}"
    
    if @total_messages > 0
      percentage = (@user_message_count.to_f / @total_messages * 100).round(2)
      puts "Percentage: #{percentage}%"
    else
      puts "Percentage: 0%"
    end
    puts "=" * 50
  end
end

# Main execution
if ARGV.length != 1
  puts "Usage: ruby runelite_chat_scanner.rb <username>"
  puts "Example: ruby runelite_chat_scanner.rb CorvusUmbra"
  exit 1
end

username = ARGV[0]
scanner = RuneLiteChatScanner.new(username)
scanner.scan_logs
