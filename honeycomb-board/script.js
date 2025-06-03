class HexGrid {
    constructor() {
        this.gameBoard = document.getElementById('gameBoard');
        this.tileDetails = document.getElementById('tileDetails');
        this.tileContent = document.getElementById('tileContent');
        this.editControls = document.getElementById('editControls');
        this.editModeToggle = document.getElementById('editModeToggle');
        this.tiles = new Map();
        this.contextMenu = null;

        // Size calculations for perfect hexagon tiling
        this.hexSize = 50; // Distance from center to corner
        this.hexWidth = this.hexSize * Math.sqrt(3); // Width of hexagon
        this.hexHeight = this.hexSize * 2; // Height of hexagon
        this.hexSpacing = 5; // Gap between adjacent tiles
        
        // Calculate offsets based on hexagon geometry
        this.xStep = this.hexWidth + this.hexSpacing;
        this.yStep = (this.hexHeight * 3/4) + (this.hexSpacing * Math.cos(Math.PI/6));
        
        // Grid dimensions
        this.gridRadius = 10; // Increased from 5 to 10 for larger initial board
        
        // Viewport position and zoom
        this.viewportX = window.innerWidth / 2;
        this.viewportY = window.innerHeight / 2;
        this.zoom = 1;
        this.isDragging = false;
        this.dragStart = { x: 0, y: 0 };
        
        // Edit mode state
        this.isEditMode = false;
        
        // Initialize the grid
        this.initializeGrid();
        
        // Add event listeners
        this.gameBoard.addEventListener('click', this.handleBoardClick.bind(this));
        this.setupDragHandlers();
        this.setupEditModeHandlers();
        this.setupZoomHandlers();
        document.addEventListener('click', this.hideContextMenu.bind(this));
        
        // Add save/load event listeners
        document.getElementById('saveBoard').addEventListener('click', () => this.saveBoard());
        document.getElementById('loadBoard').addEventListener('click', () => {
            document.getElementById('boardFile').click();
        });
        document.getElementById('boardFile').addEventListener('change', (e) => this.loadBoard(e));
        document.getElementById('shareBoard').addEventListener('click', () => this.shareBoard());

        // Create edge arrows
        this.createEdgeArrows();
    }

    initializeGrid() {
        // Clear existing tiles
        this.gameBoard.innerHTML = '';
        this.tiles.clear();

        // Create a hexagonal grid with offset rows
        for (let q = -this.gridRadius; q <= this.gridRadius; q++) {
            for (let r = -this.gridRadius; r <= this.gridRadius; r++) {
                // Offset alternate rows
                const offsetQ = q + (r % 2) * 0.5;
                // Check if this hex is within the circular radius
                if (Math.abs(offsetQ) + Math.abs(r) <= this.gridRadius * 2) {
                    this.createEmptyHex(offsetQ, r);
                }
            }
        }

        // Initialize with center tile filled
        this.toggleTile(0, 0);
    }

    createEmptyHex(q, r) {
        const key = `${q},${r}`;
        const { x, y } = this.gridToPixel(q, r);
        
        const hex = document.createElement('div');
        hex.className = 'hex';
        hex.style.left = `${x}px`;
        hex.style.top = `${y}px`;

        const content = document.createElement('div');
        content.className = 'hex-content';
        content.style.backgroundImage = 'url("https://via.placeholder.com/100x115")';
        hex.appendChild(content);

        const tileData = {
            element: hex,
            q,
            r,
            backgroundImage: content.style.backgroundImage,
            details: {
                name: `Tile ${key}`,
                description: 'Click to edit details'
            }
        };
        
        // Set initial border color
        hex.style.borderColor = tileData.details.borderColor;
        if (content) {
            content.style.borderColor = tileData.details.borderColor;
        }

        hex.addEventListener('click', (e) => {
            // Only toggle if we're in edit mode and this wasn't a drag
            if (this.isEditMode && !this.gameBoard.classList.contains('dragging')) {
                this.toggleTile(q, r);
            }
        });

        hex.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            if (this.isEditMode && hex.classList.contains('filled')) {
                this.showContextMenu(e, key);
            }
        });

        this.tiles.set(key, tileData);
        this.gameBoard.appendChild(hex);
    }

    showContextMenu(e, key) {
        this.hideContextMenu();
        
        const menu = document.createElement('div');
        menu.className = 'context-menu';
        menu.style.left = `${e.pageX}px`;
        menu.style.top = `${e.pageY}px`;

        const items = [
            {
                text: 'Edit Details',
                onClick: () => this.showTileDetails(key)
            }
        ];

        items.forEach(item => {
            const menuItem = document.createElement('div');
            menuItem.className = 'context-menu-item' + (item.className ? ` ${item.className}` : '');
            menuItem.textContent = item.text;
            menuItem.onclick = () => {
                item.onClick();
                this.hideContextMenu();
            };
            menu.appendChild(menuItem);
        });

        document.body.appendChild(menu);
        this.contextMenu = menu;

        // Adjust menu position if it would go off screen
        const menuRect = menu.getBoundingClientRect();
        if (menuRect.right > window.innerWidth) {
            menu.style.left = `${window.innerWidth - menuRect.width}px`;
        }
        if (menuRect.bottom > window.innerHeight) {
            menu.style.top = `${window.innerHeight - menuRect.height}px`;
        }
    }

    hideContextMenu() {
        if (this.contextMenu) {
            this.contextMenu.remove();
            this.contextMenu = null;
        }
    }

    toggleTile(q, r) {
        const key = `${q},${r}`;
        const tile = this.tiles.get(key);
        if (!tile) return;

        const isFilled = tile.element.classList.contains('filled');
        if (isFilled) {
            // Check if removing this tile would disconnect the board
            if (this.wouldDisconnectBoard(q, r)) {
                alert("Cannot remove this tile as it would disconnect the board");
                return;
            }
        }
        tile.element.classList.toggle('filled');
    }

    // Update wouldDisconnectBoard to only consider filled tiles
    wouldDisconnectBoard(q, r) {
        const key = `${q},${r}`;
        const tile = this.tiles.get(key);
        if (!tile || !tile.element.classList.contains('filled')) return false;

        // Count filled tiles
        const filledTiles = Array.from(this.tiles.values())
            .filter(t => t.element.classList.contains('filled'));
        
        if (filledTiles.length <= 2) return false;

        const directions = [
            { dq: 0.5, dr: 1 },   // Northeast
            { dq: 1, dr: 0 },     // East
            { dq: 0.5, dr: -1 },  // Southeast
            { dq: -0.5, dr: -1 }, // Southwest
            { dq: -1, dr: 0 },    // West
            { dq: -0.5, dr: 1 }   // Northwest
        ];

        // Get filled neighbors
        const neighbors = directions
            .map(({ dq, dr }) => `${q + dq},${r + dr}`)
            .filter(k => {
                const t = this.tiles.get(k);
                return t && t.element.classList.contains('filled');
            });

        if (neighbors.length <= 1) return false;

        // Temporarily mark this tile as not filled
        tile.element.classList.remove('filled');

        // Do a flood fill from the first neighbor
        const visited = new Set();
        const stack = [neighbors[0]];

        while (stack.length > 0) {
            const currentKey = stack.pop();
            if (visited.has(currentKey)) continue;
            visited.add(currentKey);

            const [currentQ, currentR] = currentKey.split(',').map(Number);
            
            directions.forEach(({ dq, dr }) => {
                const neighborKey = `${currentQ + dq},${currentR + dr}`;
                const neighborTile = this.tiles.get(neighborKey);
                if (neighborTile && 
                    neighborTile.element.classList.contains('filled') && 
                    !visited.has(neighborKey)) {
                    stack.push(neighborKey);
                }
            });
        }

        // Restore the tile's filled state
        tile.element.classList.add('filled');

        // Check if all filled tiles were reached
        return visited.size < filledTiles.length - 1;
    }

    // Update save/load to handle filled state
    saveBoard() {
        const boardData = {
            viewportX: this.viewportX,
            viewportY: this.viewportY,
            zoom: this.zoom,
            isEditMode: this.isEditMode,
            tiles: Array.from(this.tiles.entries())
                .filter(([_, tile]) => tile.element.classList.contains('filled'))
                .map(([key, tile]) => ({
                    key,
                    q: tile.q,
                    r: tile.r,
                    backgroundImage: tile.backgroundImage,
                    details: tile.details
                })),
        };

        const blob = new Blob([JSON.stringify(boardData, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'hex-board.json';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    loadBoard(event) {
        const file = event.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                const boardData = JSON.parse(e.target.result);
                
                // Initialize empty grid first
                this.initializeGrid();
                
                this.viewportX = boardData.viewportX || window.innerWidth / 2;
                this.viewportY = boardData.viewportY || window.innerHeight / 2;
                this.zoom = boardData.zoom || 1;
                
                if (boardData.isEditMode !== undefined) {
                    this.isEditMode = boardData.isEditMode;
                    this.updateEditModeUI();
                }
                
                // Fill and update tiles
                boardData.tiles.forEach(tileData => {
                    const { q, r, backgroundImage, details } = tileData;
                    const key = `${q},${r}`;
                    const tile = this.tiles.get(key);
                    if (tile) {
                        tile.element.classList.add('filled');
                        tile.backgroundImage = backgroundImage;
                        tile.details = details;
                        tile.element.querySelector('.hex-content').style.backgroundImage = backgroundImage;
                    }
                });

                this.updateTilePositions();
            } catch (error) {
                alert('Error loading board configuration: ' + error.message);
            }
        };
        reader.readAsText(file);
    }

    setupEditModeHandlers() {
        this.editModeToggle.addEventListener('click', () => {
            this.isEditMode = !this.isEditMode;
            this.updateEditModeUI();
        });
    }

    updateEditModeUI() {
        // Update button text and style
        this.editModeToggle.textContent = this.isEditMode ? '✏️ Edit Mode' : '🔒 View Mode';
        this.editModeToggle.classList.toggle('edit-mode', this.isEditMode);
        
        // Update other UI elements
        this.editControls.classList.toggle('active', this.isEditMode);
        this.gameBoard.classList.toggle('edit-mode', this.isEditMode);
        
        // Hide tile details when switching modes
        this.tileDetails.classList.remove('active');
        
        // Update all tiles and their add buttons
        this.tiles.forEach((tile, key) => {
            tile.element.classList.toggle('edit-mode', this.isEditMode);
        });
    }

    setupDragHandlers() {
        let isDragging = false;
        let dragStart = { x: 0, y: 0 };
        let dragStartTime = 0;
        const DRAG_THRESHOLD = 200; // milliseconds

        this.gameBoard.addEventListener('mousedown', (e) => {
            // Only start drag if it's a left click
            if (e.button !== 0) return;

            isDragging = false;
            dragStartTime = Date.now();
            dragStart = {
                x: e.clientX - this.viewportX,
                y: e.clientY - this.viewportY
            };

            const handleMouseMove = (e) => {
                const dx = e.clientX - (dragStart.x + this.viewportX);
                const dy = e.clientY - (dragStart.y + this.viewportY);
                const distance = Math.sqrt(dx * dx + dy * dy);

                if (distance > 5) { // 5px threshold for drag
                    isDragging = true;
                    this.gameBoard.classList.add('dragging');
                }

                if (isDragging) {
                    this.viewportX = e.clientX - dragStart.x;
                    this.viewportY = e.clientY - dragStart.y;
                    this.updateTilePositions();
                }
            };

            const handleMouseUp = (e) => {
                window.removeEventListener('mousemove', handleMouseMove);
                window.removeEventListener('mouseup', handleMouseUp);
                
                if (isDragging) {
                    e.preventDefault();
                    e.stopPropagation();
                }
                
                isDragging = false;
                this.gameBoard.classList.remove('dragging');
            };

            window.addEventListener('mousemove', handleMouseMove);
            window.addEventListener('mouseup', handleMouseUp);
        });

        // Prevent default drag behavior
        this.gameBoard.addEventListener('dragstart', (e) => e.preventDefault());
    }

    setupZoomHandlers() {
        // Add zoom buttons to controls
        const zoomControls = document.createElement('div');
        zoomControls.className = 'zoom-controls';
        zoomControls.innerHTML = `
            <button id="zoomIn">+</button>
            <button id="zoomOut">-</button>
        `;
        this.editControls.appendChild(zoomControls);

        // Add wheel zoom
        this.gameBoard.addEventListener('wheel', (e) => {
            e.preventDefault();
            const zoomFactor = 1.1;
            const delta = e.deltaY > 0 ? 1/zoomFactor : zoomFactor;
            this.setZoom(this.zoom * delta);
        });

        // Add button zoom
        document.getElementById('zoomIn').addEventListener('click', () => {
            this.setZoom(this.zoom * 1.1);
        });

        document.getElementById('zoomOut').addEventListener('click', () => {
            this.setZoom(this.zoom * 0.9);
        });
    }

    setZoom(newZoom) {
        // Clamp zoom between 0.5 and 2
        this.zoom = Math.max(0.5, Math.min(2, newZoom));
        
        // Update hex sizes while keeping spacing consistent
        const baseSize = 50;
        this.hexSize = baseSize * this.zoom;
        this.hexWidth = this.hexSize * Math.sqrt(3);
        this.hexHeight = this.hexSize * 2;
        this.xStep = this.hexWidth + this.hexSpacing;
        this.yStep = (this.hexHeight * 3/4) + (this.hexSpacing * Math.cos(Math.PI/6));

        // Update CSS variables for hex sizing
        this.gameBoard.style.setProperty('--hex-size', `${this.hexSize}px`);
        this.gameBoard.style.setProperty('--hex-width', `${this.hexWidth}px`);
        this.gameBoard.style.setProperty('--hex-height', `${this.hexHeight}px`);
        
        this.updateTilePositions();
    }

    // Convert grid coordinates to pixel coordinates
    gridToPixel(q, r) {
        const x = q * this.xStep;
        const y = -r * this.yStep;
        return { 
            x: x + this.viewportX, 
            y: y + this.viewportY 
        };
    }

    // Update all tile positions based on viewport
    updateTilePositions() {
        this.tiles.forEach((tile, key) => {
            const { x, y } = this.gridToPixel(tile.q, tile.r);
            tile.element.style.left = `${x}px`;
            tile.element.style.top = `${y}px`;
        });
    }

    // Show tile details in the side panel
    showTileDetails(key) {
        const tile = this.tiles.get(key);
        if (!tile) return;

        let content = `
            <div class="tile-details-content">
                <div class="details-section">
                    <div class="details-header">
                        <h3>Details</h3>
                        ${this.isEditMode ? `
                            <div class="details-actions">
                                <button class="edit-link" onclick="hexGrid.startEditing('${key}', 'description')">Edit</button>
                                <button class="reset-link" onclick="hexGrid.resetTile('${key}')">Reset</button>
                            </div>
                        ` : ''}
                    </div>
                    <div class="details-field">
                        <span class="details-label">Description:</span>
                        <div class="details-value" id="tileDescription">
                            ${tile.details.description}
                        </div>
                    </div>
                </div>
                ${this.isEditMode ? `
                    <div class="item-search-section">
                        <h3>OSRS Item Search</h3>
                        <div class="search-container">
                            <input type="text" id="itemSearch" placeholder="Search for an OSRS item...">
                            <button onclick="hexGrid.searchOSRSItem('${key}')">Search</button>
                        </div>
                        <div id="searchResults" class="search-results"></div>
                    </div>
                ` : ''}
                <div class="image-section">
                    <h3>Image</h3>
                    <div class="image-preview">
                        <img src="${tile.backgroundImage.replace(/url\(['"](.+)['"]\)/, '$1')}" alt="Tile preview">
                    </div>
                    ${this.isEditMode ? `<button onclick="hexGrid.changeTileImage('${key}')">Change Image</button>` : ''}
                </div>
            </div>
        `;

        this.tileContent.innerHTML = content;
        this.tileDetails.classList.add('active');
    }

    async searchOSRSItem(key) {
        const searchInput = document.getElementById('itemSearch');
        const searchTerm = searchInput.value.trim();
        if (!searchTerm) return;

        const searchResults = document.getElementById('searchResults');
        searchResults.innerHTML = '<div class="loading">Searching...</div>';

        try {
            // Use the OSRS Wiki API to search for items
            const response = await fetch(`https://oldschool.runescape.wiki/api.php?action=query&list=search&srsearch=${encodeURIComponent(searchTerm)}&format=json&origin=*`);
            const data = await response.json();
            
            if (data.query && data.query.search) {
                const results = data.query.search;
                if (results.length > 0) {
                    // Get the first result and fetch its image
                    const pageId = results[0].pageid;
                    const imageResponse = await fetch(`https://oldschool.runescape.wiki/api.php?action=query&prop=pageimages&piprop=original&pageids=${pageId}&format=json&origin=*`);
                    const imageData = await imageResponse.json();
                    
                    const page = imageData.query.pages[pageId];
                    if (page.original) {
                        const imageUrl = page.original.source;
                        const wikiUrl = `https://oldschool.runescape.wiki/w/${encodeURIComponent(results[0].title.replace(/ /g, '_'))}`;
                        
                        // Update the tile with the item image and wiki link
                        const tile = this.tiles.get(key);
                        if (tile) {
                            tile.backgroundImage = `url("${imageUrl}")`;
                            tile.element.querySelector('.hex-content').style.backgroundImage = tile.backgroundImage;
                            tile.details.description = `<a href="${wikiUrl}" target="_blank">${results[0].title}</a>`;
                            this.showTileDetails(key);
                        }
                    }
                } else {
                    searchResults.innerHTML = '<div class="no-results">No items found</div>';
                }
            }
        } catch (error) {
            console.error('Error searching for OSRS item:', error);
            searchResults.innerHTML = '<div class="error">Error searching for item</div>';
        }
    }

    updateBorderColor(key, color) {
        const tile = this.tiles.get(key);
        if (!tile) return;

        tile.details.borderColor = color;
        tile.element.style.setProperty('--border-color', color);
        this.showTileDetails(key);
    }

    resetTile(key) {
        const tile = this.tiles.get(key);
        if (!tile) return;

        // Reset to default values
        tile.backgroundImage = 'url("https://via.placeholder.com/100x115")';
        tile.element.querySelector('.hex-content').style.backgroundImage = tile.backgroundImage;
        tile.details.description = 'Click to edit details';

        // Refresh the tile details view
        this.showTileDetails(key);
    }

    // Handle clicks on the game board
    handleBoardClick(e) {
        if (e.target === this.gameBoard) {
            this.tileDetails.classList.remove('active');
        } else if (e.target.closest('.hex')) {
            const hex = e.target.closest('.hex');
            const key = Array.from(this.tiles.keys()).find(k => this.tiles.get(k).element === hex);
            if (key) {
                this.showTileDetails(key);
            }
        }
    }

    // Edit tile details
    startEditing(key, field) {
        const tile = this.tiles.get(key);
        if (!tile) return;

        const container = document.getElementById('tileDescription');
        const currentValue = tile.details[field];
        
        container.innerHTML = `
            <div class="edit-field">
                <textarea class="edit-textarea">${currentValue}</textarea>
                <div class="edit-actions">
                    <button onclick="hexGrid.saveEdit('${key}', '${field}')">Save</button>
                    <button onclick="hexGrid.cancelEdit('${key}', '${field}')">Cancel</button>
                </div>
            </div>
        `;
    }

    saveEdit(key, field) {
        const tile = this.tiles.get(key);
        if (!tile) return;

        const textarea = document.querySelector('.edit-textarea');
        const newValue = textarea.value.trim();
        
        if (newValue) {
            tile.details[field] = newValue;
            this.showTileDetails(key);
        }
    }

    cancelEdit(key, field) {
        this.showTileDetails(key);
    }

    // Change tile background image
    changeTileImage(key) {
        const tile = this.tiles.get(key);
        if (!tile) return;

        const input = document.createElement('input');
        input.type = 'text';
        input.id = 'imageUrl';
        input.value = tile.backgroundImage.replace(/url\(['"](.+)['"]\)/, '$1');
        input.placeholder = 'Enter image URL';
        
        const container = document.querySelector('.image-section');
        const oldButton = container.querySelector('button');
        const newButton = document.createElement('button');
        newButton.textContent = 'Save Image';
        
        oldButton.replaceWith(input);
        input.parentNode.insertBefore(newButton, input.nextSibling);
        
        newButton.onclick = () => {
            const imageUrl = input.value.trim();
            if (imageUrl) {
                tile.backgroundImage = `url("${imageUrl}")`;
                tile.element.querySelector('.hex-content').style.backgroundImage = tile.backgroundImage;
                this.showTileDetails(key);
            }
        };
    }

    // Remove a tile from the grid
    removeTile(q, r) {
        const key = `${q},${r}`;
        const tile = this.tiles.get(key);
        if (!tile) return;

        // Don't allow removing the last tile
        if (this.tiles.size <= 1) {
            alert("Cannot remove the last tile on the board");
            return;
        }

        // Check if removing this tile would disconnect the board
        if (this.wouldDisconnectBoard(q, r)) {
            alert("Cannot remove this tile as it would disconnect the board");
            return;
        }

        // Remove the tile element from the DOM
        tile.element.remove();
        // Remove the tile from our collection
        this.tiles.delete(key);
        // Hide the details panel
        this.tileDetails.classList.remove('active');
    }

    createEdgeArrows() {
        const directions = [
            { class: 'top', symbol: '↑', expand: () => this.expandBoard('top') },
            { class: 'bottom', symbol: '↓', expand: () => this.expandBoard('bottom') },
            { class: 'left', symbol: '←', expand: () => this.expandBoard('left') },
            { class: 'right', symbol: '→', expand: () => this.expandBoard('right') }
        ];

        directions.forEach(({ class: className, symbol, expand }) => {
            const arrow = document.createElement('div');
            arrow.className = `edge-arrow ${className}`;
            arrow.textContent = symbol;
            arrow.addEventListener('click', expand);
            this.gameBoard.appendChild(arrow);
        });
    }

    expandBoard(direction) {
        const expansionSize = 5; // Number of rows/columns to add
        const oldRadius = this.gridRadius;
        this.gridRadius += expansionSize;

        // Create new hexes in the expanded area
        for (let q = -this.gridRadius; q <= this.gridRadius; q++) {
            for (let r = -this.gridRadius; r <= this.gridRadius; r++) {
                const offsetQ = q + (r % 2) * 0.5;
                const key = `${offsetQ},${r}`;
                
                // Only create hexes in the new area
                if (Math.abs(offsetQ) + Math.abs(r) <= this.gridRadius * 2 &&
                    Math.abs(offsetQ) + Math.abs(r) > oldRadius * 2) {
                    this.createEmptyHex(offsetQ, r);
                }
            }
        }

        // Adjust viewport to keep the center visible
        const viewportAdjustment = expansionSize * this.yStep;
        switch (direction) {
            case 'top':
                this.viewportY += viewportAdjustment;
                break;
            case 'bottom':
                this.viewportY -= viewportAdjustment;
                break;
            case 'left':
                this.viewportX += viewportAdjustment;
                break;
            case 'right':
                this.viewportX -= viewportAdjustment;
                break;
        }

        this.updateTilePositions();
    }

    shareBoard() {
        const boardData = {
            viewportX: this.viewportX,
            viewportY: this.viewportY,
            zoom: this.zoom,
            tiles: Array.from(this.tiles.entries())
                .filter(([_, tile]) => tile.element.classList.contains('filled'))
                .map(([key, tile]) => ({
                    key,
                    q: tile.q,
                    r: tile.r,
                    backgroundImage: tile.backgroundImage,
                    details: tile.details
                }))
        };

        // Convert to base64 for URL
        const encodedData = btoa(JSON.stringify(boardData));
        const shareUrl = `${window.location.origin}/view.html?board=${encodedData}`;

        // Create a temporary input to copy the URL
        const tempInput = document.createElement('input');
        tempInput.value = shareUrl;
        document.body.appendChild(tempInput);
        tempInput.select();
        document.execCommand('copy');
        document.body.removeChild(tempInput);

        // Show a notification
        alert('Share link copied to clipboard!');
    }
}

// Initialize the hex grid
const hexGrid = new HexGrid(); 