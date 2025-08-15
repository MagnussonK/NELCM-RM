// --- Global Variables and Utility Functions ---
        let allData = []; // Stores all data fetched from the backend
        let currentView = 'home'; // Tracks the currently active view
        let currentFamilyId = null; // Used by familyDetails, recordDetails, manageSecondaryMembers
        let currentMemberName = null; // Used by recordDetails
        let currentMemberLastName = null; // Used by recordDetails
        let currentIsPrimary = false; // Used by recordDetails to determine editable fields

        // Global variables for Add Visit View
        let currentAddVisitMemberId = null;
        let currentAddVisitName = null;
        let currentAddVisitLastName = null;

        // Global variables for Member Visits View
        let currentVisitsMemberId = null;
        let currentVisitsMemberName = null;
        let currentVisitsMemberLastName = null;
        let currentVisitsMemStartDate = null; // Membership start date for the family
        let currentCalendarDate = new Date(); // Tracks the month/year displayed in the calendar
        let allMemberVisitedDates = []; // Stores all visit dates for the current member as Date objects

        // --- Global Configuration ---
		
		window.BASE_API_URL = 'https://5cdg8ds4u2.execute-api.us-east-1.amazonaws.com/api';

        
		// Get common DOM elements
		const messageBox = document.getElementById('messageBox');
        const globalLoadingIndicator = document.getElementById('globalLoadingIndicator');
		const familyDetailsContent = document.getElementById('familyDetailsContent');


        // Get all view sections
        const homeView = document.getElementById('homeView');
        const addRecordView = document.getElementById('addRecordView');
        const familyDetailsView = document.getElementById('familyDetailsView');
        const recordDetailsView = document.getElementById('recordDetailsView');
        const manageSecondaryMembersView = document.getElementById('manageSecondaryMembersView');
        const addVisitView = document.getElementById('addVisitView'); // New
        const memberVisitsView = document.getElementById('memberVisitsView'); // New
        
        // --- UI Utility Functions ---

        /**
         * Shows the global loading indicator.
         */
        function showLoadingIndicator() {
            // Assumes you have an element with the id 'globalLoadingIndicator'
            const globalLoadingIndicator = document.getElementById('globalLoadingIndicator');
            if (globalLoadingIndicator) {
                globalLoadingIndicator.classList.remove('hidden');
            }
        }
        
        /**
         * Hides the global loading indicator.
         */
        function hideLoadingIndicator() {
            const globalLoadingIndicator = document.getElementById('globalLoadingIndicator');
            if (globalLoadingIndicator) {
                globalLoadingIndicator.classList.add('hidden');
            }
        }

        /**
         * Switches the active view.
         * @param {string} viewId - The ID of the view to show (e.g., 'homeView', 'addRecordView').
         */
        function showView(viewId) {
            const views = [homeView, addRecordView, familyDetailsView, recordDetailsView, manageSecondaryMembersView, addVisitView, memberVisitsView];
            views.forEach(view => {
                if (view.id === viewId) {
                    view.classList.remove('hidden');
                } else {
                    view.classList.add('hidden');
                }
            });
            currentView = viewId;
            // Scroll to top of the new view
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        /**
         * Displays a message to the user (success or error).
         * @param {string} message - The message to display.
         * @param {string} type - 'success' or 'error'.
         */
        function showMessage(message, type) {
            messageBox.textContent = message;
            messageBox.classList.remove('hidden', 'bg-green-100', 'text-green-800', 'bg-red-100', 'text-red-800');
            messageBox.classList.add('opacity-100');
            if (type === 'success') {
                messageBox.classList.add('bg-green-100', 'text-green-800');
            } else if (type === 'error') {
                messageBox.classList.add('bg-red-100', 'text-red-800');
            }
            setTimeout(() => {
                messageBox.classList.remove('opacity-100');
                messageBox.classList.add('opacity-0');
                setTimeout(() => {
                    messageBox.classList.add('hidden');
                }, 300);
            }, 5000);
        }

        /**
         * Helper function to get the ID from a record object, trying common casing variations.
         * @param {Object} record - The record object.
         * @returns {string|undefined} The ID of the record.
         */
        function getRecordId(record) {
            if (record.member_id !== undefined) return record.member_id;
            if (record.id !== undefined) return record.id;
            if (record.ID !== undefined) return record.ID;
            if (record.Id !== undefined) return record.Id;
            return undefined;
        }

        /**
         * Parses a date string robustly, handling various formats and returning a valid Date object or null.
         * @param {string} dateString - The date string to parse.
         * @returns {Date|null} A valid Date object (UTC) or null if parsing fails.
         */
        function parseDateRobustly(dateString) {
            if (!dateString || typeof dateString !== 'string' || dateString.trim() === '') {
                return null;
            }
            dateString = dateString.trim();
            let date;

            // Try parsing as pyridine-MM-dd first (from input type="date" or backend)
            if (/^\d{4}-\d{2}-\d{2}$/.test(dateString)) {
                // This is already handled as UTC for consistency
                const parts = dateString.split('-');
                date = new Date(Date.UTC(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2])));
            } 
            // Then try parsing common GMT/UTC/ISO formats
            else if (dateString.includes('GMT') || dateString.includes('UTC') || dateString.includes('+') || dateString.includes('-') || dateString.includes('T')) {
                date = new Date(dateString); // This will parse it as UTC if 'GMT' is present, then convert to local timezone for display by default Date.toString()
            } 
            // Fallback for just date string, assume UTC midnight to avoid timezone issues
            else {
                date = new Date(dateString + 'T00:00:00Z'); // This explicitly creates a UTC date
            }
            
            return !isNaN(date.getTime()) ? date : null;
        }

        /**
         * Formats a date object into MM/DD/YYYY.
         * @param {Date|null} dateObj - The Date object to format.
         * @returns {string} Formatted date string or 'N/A'.
         */
        function formatDate(dateObj) {
            if (!dateObj) return 'N/A';
            try {
                const year = dateObj.getUTCFullYear();
                const month = (dateObj.getUTCMonth() + 1).toString().padStart(2, '0');
                const day = dateObj.getUTCDate().toString().padStart(2, '0');
                return `${month}/${day}/${year}`;
            } catch (e) {
                console.error("Error formatting date:", dateObj, e);
                return 'N/A';
            }
        }

        /**
         * Formats a Date object into ISO 8601 pyridine-MM-dd for input[type="date"].
         * @param {Date|null} dateObj - The Date object to format.
         * @returns {string} Formatted date string or empty string.
         */
        function formatDateForInput(dateObj) {
            if (!dateObj) return '';
            try {
                const year = dateObj.getUTCFullYear();
                const month = (dateObj.getUTCMonth() + 1).toString().padStart(2, '0');
                const day = dateObj.getUTCDate().toString().padStart(2, '0');
                return `${year}-${month}-${day}`;
            } catch (e) {
                console.error("Error formatting date for input:", dateObj, e);
                return '';
            }
        }

        /**
         * Formats a Date object into ISO 8601 pyridine-MM-ddTHH:MM for input[type="datetime-local"].
         * @param {Date|null} dateObj - The Date object to format.
         * @returns {string} Formatted datetime string or empty string.
         */
        function formatDateTimeLocalForInput(dateObj) {
            if (!dateObj) return '';
            try {
                // Ensure the date object is treated as local time for input display
                const year = dateObj.getFullYear();
                const month = (dateObj.getMonth() + 1).toString().padStart(2, '0');
                const day = dateObj.getDate().toString().padStart(2, '0');
                const hours = dateObj.getHours().toString().padStart(2, '0');
                const minutes = dateObj.getMinutes().toString().padStart(2, '0');
                return `${year}-${month}-${day}T${hours}:${minutes}`;
            } catch (e) {
                console.error("Error formatting datetime for input:", dateObj, e);
                return '';
            }
        }


        /**
         * Formats a 10-digit phone number string into (###) ###-####.
         * @param {string} phoneNumberString - The raw phone number string (digits only).
         * @returns {string} Formatted phone number or original string if invalid.
         */
        function formatPhoneNumber(phoneNumberString) {
            if (!phoneNumberString) return 'N/A';
            const cleaned = ('' + phoneNumberString).replace(/\D/g, ''); // Remove non-digits
            const match = cleaned.match(/^(\d{3})(\d{3})(\d{4})$/);
            if (match) {
                return '(' + match[1] + ') ' + match[2] + '-' + match[3];
            }
            return phoneNumberString; // Return original if it doesn't match 10 digits
        }

        // --- Home View Logic ---
        const homeFetchDataBtn = document.getElementById('homeFetchDataBtn');
        const homeAddRecordBtn = document.getElementById('homeAddRecordBtn');
        const homeLastNameSearchInput = document.getElementById('homeLastNameSearch');
        const homeDataResultsDiv = document.getElementById('homeDataResults');
        const homeRefreshSpinner = document.getElementById('homeRefreshSpinner');
        const homeMemberCountSpan = document.getElementById('homeMemberCount');
        const homeFamilyCountSpan = document.getElementById('homeUniqueMemberCount');
        const homeVisitsTodayCountSpan = document.getElementById('homeVisitsTodayCount');
        const homeGenerateReportBtn = document.getElementById('homeGenerateReportBtn');
        const showInactiveToggle = document.getElementById('showInactiveToggle');
        // --- NEW: Get the new button ---
        const homeSendEmailsBtn = document.getElementById('homeSendEmailsBtn');


        /**
         * Calculates and updates the display of total active family members and total active families.
         * @param {Array<Object>} allFetchedData - The array of all member records (unfiltered).
         */
        function updateCounts(allFetchedData) {
            let activeFamilyMemberIds = new Set();
            let totalActiveFamilyMembersCount = 0;

            const familiesMap = allFetchedData.reduce((acc, member) => {
                const memberId = member.member_id;
                if (!acc[memberId]) {
                    acc[memberId] = {
                        members: [],
                        primaryActive: false
                    };
                }
                acc[memberId].members.push(member);
                if (member.primary_member === true && member.active_flag === true) {
                    acc[memberId].primaryActive = true;
                }
                return acc;
            }, {});

            for (const memberId in familiesMap) {
                if (familiesMap[memberId].primaryActive) {
                    activeFamilyMemberIds.add(memberId);
                    totalActiveFamilyMembersCount += familiesMap[memberId].members.length;
                }
            }
            
            homeMemberCountSpan.textContent = `Total Active Family Members: ${totalActiveFamilyMembersCount}`;
            homeFamilyCountSpan.textContent = `Total Active Families: ${activeFamilyMemberIds.size}`;
        }
		
		// --- Today's Visitors Modal Logic ---
        const todaysVisitsModal = document.getElementById('todaysVisitsModal');
        const closeTodaysVisitsModalBtn = document.getElementById('closeTodaysVisitsModalBtn');
        const todaysVisitsTableBody = document.getElementById('todaysVisitsTableBody');
        const noVisitsMessage = document.getElementById('noVisitsMessage');
        const visitsTodayContainer = document.getElementById('visitsTodayContainer');

        /**
         * Fetches and displays the list of visitors for the current day in a modal.
         */
        async function showTodaysVisitors() {
            showLoadingIndicator();
            try {
                // Use the new API endpoint to get today's visits
				const response = await apiFetch('/visits/today/grouped');
				if (!response.ok) {
					const errorData = await response.json();
					throw new Error(`HTTP error! Status: ${response.status}. Details: ${errorData.error || 'Unknown error'}`);
				}

				const families = await response.json();
				todaysVisitsTableBody.innerHTML = ''; // Clear previous data

				if (families.length === 0) {
					noVisitsMessage.classList.remove('hidden');
					todaysVisitsTableBody.parentElement.classList.add('hidden');
				} else {
				noVisitsMessage.classList.add('hidden');
				todaysVisitsTableBody.parentElement.classList.remove('hidden');

				families.forEach(fam => {
					const row = `
						<tr>
							<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-left">
								${fam.name} ${fam.last_name}
							</td>
							<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-left">
								${fam.visitors}
							</td>
						</tr>`;
					todaysVisitsTableBody.insertAdjacentHTML('beforeend', row);
				});
			}

			todaysVisitsModal.classList.remove('hidden');
			
            } catch (error) {
                console.error('Error fetching today\'s visitors:', error);
                showMessage(`Failed to fetch today's visitors: ${error.message}`, 'error');
            } finally {
                hideLoadingIndicator();
            }
        }

        // Event Listeners for the modal
        visitsTodayContainer.addEventListener('click', showTodaysVisitors);
        closeTodaysVisitsModalBtn.addEventListener('click', () => {
            todaysVisitsModal.classList.add('hidden');
        });

        // Close modal if user clicks on the background overlay
        todaysVisitsModal.addEventListener('click', (event) => {
            if (event.target === todaysVisitsModal) {
                todaysVisitsModal.classList.add('hidden');
            }
        });
        
        /**
         * Fetches and displays the count of visits for today.
         */
        async function fetchVisitsTodayCount() {
            // This is the correct URL for the API endpoint
            			
            try {
                // Use the same variable name here
                const response = await apiFetch('/visits/today/count');
        
                if (!response.ok) {
                    const errorText = await response.text();
                    let errorMessage = `HTTP error! Status: ${response.status}.`;
                    try {
                        const errorData = JSON.parse(errorText);
                        errorMessage += ` Details: ${errorData.error || 'Unknown error'}`;
                    } catch (jsonError) {
                        errorMessage += ` Response: "${errorText.substring(0, 100)}..." (Not JSON)`;
                    }
                    throw new Error(errorMessage);
                }
        
                const contentType = response.headers.get("content-type");
                if (!contentType || !contentType.includes("application/json")) {
                    const errorText = await response.text();
                    throw new Error(`Expected JSON, but received "${contentType}". Response: "${errorText.substring(0, 100)}..."`);
                }
        
                const data = await response.json();
                homeVisitsTodayCountSpan.textContent = `Visits Today: ${data.count}`;
            } catch (error) {
                console.error('Error fetching visits today count:', error);
                homeVisitsTodayCountSpan.textContent = `Visits Today: Error`;
        
                // Also fix the variable name in the error message for accurate debugging
                if (error.message.includes('404')) {
                    showMessage(`Failed to fetch today's visits: The backend endpoint was not found (404). Please ensure the API URL is correct.`, 'error');
                } else {
                    showMessage(`Failed to fetch today's visits: ${error.message}. Please check the backend server.`, 'error');
                }
            }
        }

        /**
         * Triggers the backend endpoint to update expired memberships.
         */
        async function triggerMembershipExpiryUpdate() {
            console.log('Triggering backend membership expiry update...');
            try {
                const response = await apiFetch('/update_expired_memberships', { method: 'PUT' });
                if (!response.ok) {
                    const errorData = await response.json();
                    console.error('Backend expiry update error:', errorData);
                } else {
                    const result = await response.json();
                    console.log('Backend expiry update successful:', result.message);
                }
            } catch (error) {
                console.error('Error calling backend expiry update:', error);
            }
        }

        /**
         * Checks if a record (primary member) has any missing critical information.
         * @param {Object} record - The primary member record object.
         * @returns {boolean} True if any critical field is null/undefined/empty, false otherwise.
         */
        function hasMissingData(record) {
            const fieldsToCheck = [
                'email', 'address', 'city', 'state', 'zip_code'
            ];
            for (const field of fieldsToCheck) {
                if (record[field] === null || record[field] === undefined || (typeof record[field] === 'string' && record[field].trim() === '')) {
                    return true;
                }
            }
            return false;
        }

        /**
         * Renders the provided data into the home view table.
         * @param {Array<Object>} dataToRender - The array of data objects to display.
         */
		function renderHomeTable(dataToRender) {
            if (!dataToRender || dataToRender.length === 0) {
                homeDataResultsDiv.innerHTML = '<p class="text-center text-gray-500 py-4">No data found or no results match your search.</p>';
                return;
            }

            const displayHeaders = ['info_status', 'last_name', 'name', 'membership_expires', 'active_flag']; 
            
            let tableHtml = '<table class="min-w-full divide-y divide-gray-200 rounded-lg overflow-hidden shadow-sm">';
            tableHtml += '<thead class="bg-gray-200"><tr class="text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">';
            
            displayHeaders.forEach(header => {
                let headerText = header.replace(/_/g, ' ');
                let headerClass = 'px-6 py-3';

                if (header === 'info_status') {
                    headerText = '';
                    headerClass = 'px-2 py-2 text-center';
                } else if (header === 'active_flag') { 
                    headerText = 'Status';
                } else if (header === 'last_name') {
                    headerText = 'Last Name';
                } else if (header === 'name') {
                    headerText = 'First Name';
                } else if (header === 'membership_expires') {
                    headerText = 'Membership Expires';
                    headerClass += ' text-right'; 
                }
                tableHtml += `<th class="${headerClass}">${headerText}</th>`;
            });
            tableHtml += '<th class="px-6 py-3 text-center"></th>'; // Empty header for check-in button
            tableHtml += '</tr></thead>';
            tableHtml += '<tbody class="bg-white divide-y divide-gray-200">';
            
            const today = new Date();
            today.setUTCHours(0, 0, 0, 0); 

            const todayMonth = today.getUTCMonth();
            const todayYear = today.getUTCFullYear();

            dataToRender.forEach(row => {
                const rowId = getRecordId(row);
                let rowClass = '';

                if (row.founding_family !== true && row.membership_expires) {
                    const expirationDate = parseDateRobustly(row.membership_expires);
                    if (expirationDate) {
                        expirationDate.setUTCHours(0, 0, 0, 0);
                        if (expirationDate < today) {
                            rowClass += 'expired-membership-row ';
                        } else if (expirationDate.getUTCMonth() === todayMonth && expirationDate.getUTCFullYear() === todayYear) {
                            rowClass += 'expiring-soon-row ';
                        }
                    }
                }

                if (row.founding_family === true) {
                    rowClass += 'founding-family-row ';
                }

                const familyMembers = allData.filter(member => member.member_id === rowId);
                const isBirthdayInFamily = familyMembers.some(member => {
                    if (!member.birthday) return false;
                    const birthdayDate = parseDateRobustly(member.birthday);
                    if (!birthdayDate) return false;
                    const memberMonth = birthdayDate.getUTCMonth();
                    const memberDay = birthdayDate.getUTCDate();
                    return memberMonth === todayMonth && memberDay === today.getUTCDate();
                });

                if (isBirthdayInFamily) {
                    rowClass += 'sparkly-birthday-row ';
                }
                
                const hasMissing = hasMissingData(row);
                if (hasMissing) {
                    rowClass += 'missing-info-row ';
                }
                
                tableHtml += `<tr data-id="${rowId}" class="cursor-pointer hover:bg-gray-50 ${rowClass.trim()}">`;
                
                displayHeaders.forEach(header => {
                    let value = row[header];
                    let displayValue = 'N/A';
                    let cellClass = 'px-6 py-4 whitespace-nowrap text-gray-700';

                    if (header === 'info_status') {
                        cellClass = 'px-2 py-3 text-center flex items-center justify-center gap-2';
                        let statusIcons = '';

                        // --- MODIFIED ICON LOGIC ---
                        // If email has NOT been sent and it's not a founding family, show the new SVG icon
                        if (!row.renewal_email_sent && !row.founding_family) {
                            statusIcons += `<span title="Renewal notice has not been sent" class="inline-flex items-center justify-center h-6 w-6 rounded-full bg-red-100 text-red-800">
                                                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" style="stroke: #7f1d1d;"/>
                                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 6l12 12" style="stroke: #ef4444;" />
                                                </svg>
                                            </span>`;
                        }

                        // If the record is missing contact info, show the warning icon
                        if (hasMissing) {
                            statusIcons += `<span title="Missing important information" class="inline-flex items-center justify-center h-6 w-6 rounded-full bg-yellow-100 text-yellow-800">
                                                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                                                </svg>
                                            </span>`;
                        }
                        displayValue = statusIcons;

                    } else if (header === 'membership_expires') {
                        cellClass += ' text-right';
                        if (row.founding_family === true) {
                            displayValue = 'Founding Family';
                            cellClass += ' font-bold text-purple-700';
                        } else if (value) {
                             const date = parseDateRobustly(value);
                             displayValue = formatDate(date);
                        }
                    } else if (value !== null && value !== undefined && String(value).trim() !== '') {
                        
						if (header === 'active_flag') {
                           if (row.founding_family === true) {
                               displayValue = 'Active';
                           } else {
                              const expirationDate = parseDateRobustly(row.membership_expires);
                              if (expirationDate && expirationDate >= today) {
                                  displayValue = 'Active';
                              } else {
                                  displayValue = row.active_flag === true ? 'Active' : 'Inactive';
                              }
                           }
                        }
				        else {
                            displayValue = String(value).trim();
                            if (displayValue === '') displayValue = 'N/A';
                        }
                    }

                    tableHtml += `<td class="${cellClass}">${displayValue}</td>`;
                });
                
                tableHtml += `<td class="px-6 py-4 whitespace-nowrap text-center">
                                    <button type="button" 
                                            onclick="event.stopPropagation(); checkInFamily('${rowId}')" 
                                            class="action-button btn-primary text-xs px-3 py-1 bg-green-600 hover:bg-green-700">
                                        Check-In Family
                                    </button>
                                </td>`;
                tableHtml += '</tr>';
            });
            tableHtml += '</tbody></table>';
            homeDataResultsDiv.innerHTML = tableHtml;

            document.querySelectorAll('#homeDataResults tbody tr').forEach(rowElement => {
                rowElement.addEventListener('click', (event) => {
                    const idFromDataAttribute = rowElement.dataset.id;
                    const record = allData.find(item => getRecordId(item) === idFromDataAttribute && item.primary_member === true);

                    if (record) {
                        currentFamilyId = idFromDataAttribute;
                        renderFamilyDetailsView();
                    } else {
                        console.warn('Home View: Primary Record not found for ID:', idFromDataAttribute, 'during double-click. allData:', allData);
                        showMessage('Could not find primary record for this family.', 'error');
                    }
                });
            });
        }
        /**
         * Filters and sorts the displayed data based on the last name search input
         * and the "show inactive" toggle for the home view.
         */
        function filterHomeData() {
            const searchTerm = homeLastNameSearchInput.value.toLowerCase().trim();
            const showInactive = showInactiveToggle.checked;

            let matchedFamilyIds = new Set();

            allData.forEach(member => {
                const memberLastName = (member.last_name || '').toLowerCase();
                if (memberLastName.includes(searchTerm)) {
                    if (!showInactive) {
                        const primaryMemberOfFamily = allData.find(p => p.member_id === member.member_id && p.primary_member === true);
                        if (primaryMemberOfFamily && primaryMemberOfFamily.active_flag === true) {
                            matchedFamilyIds.add(member.member_id);
                        }
                    } else {
                        matchedFamilyIds.add(member.member_id);
                    }
                }
            });

            let filteredPrimaryMembersToRender = allData.filter(item =>
                item.primary_member === true && matchedFamilyIds.has(item.member_id)
            );

            if (searchTerm === '') {
                filteredPrimaryMembersToRender = allData.filter(item => item.primary_member === true);
                if (!showInactive) {
                    filteredPrimaryMembersToRender = filteredPrimaryMembersToRender.filter(item => item.active_flag === true);
                }
            }


            filteredPrimaryMembersToRender.sort((a, b) => {
                const lastNameA = (a.last_name || '').toLowerCase();
                const lastNameB = (b.last_name || '').toLowerCase();
                if (lastNameA < lastNameB) return -1;
                if (lastNameA > lastNameB) return 1;
                
                const nameA = (a.name || '').toLowerCase();
                const nameB = (b.name || '').toLowerCase();
                if (nameA < nameB) return -1;
                if (nameA > nameB) return 1;

                const memberIdA = (a.member_id || '').toLowerCase();
                const memberIdB = (b.member_id || '').toLowerCase();
                if (memberIdA < memberIdB) return -1;
                if (memberIdA > memberIdB) return 1;
                
                return 0;
            });

            renderHomeTable(filteredPrimaryMembersToRender);
        }

        /**
         * Fetches all data from the backend API.
         */
        /**
         * Fetches all necessary data from the backend to initialize the application.
         */
		async function fetchAllData() {
            globalLoadingIndicator.classList.remove('hidden');
            homeFetchDataBtn.disabled = true;
            homeRefreshSpinner.classList.remove('hidden');
        
            try {
                const response = await apiFetch('/data');
        
                if (!response.ok) {
                    let errorDetails = 'The server returned an error response.';
                    try {
                        // Safely attempt to parse the error response as JSON
                        const errorData = await response.json();
                        errorDetails = errorData.error || JSON.stringify(errorData);
                    } catch (jsonError) {
                        // If the response wasn't JSON, use the status text as a fallback
                        errorDetails = response.statusText || 'Could not parse error response.';
                    }
                    throw new Error(`HTTP error! Status: ${response.status}. Details: ${errorDetails}`);
                }

                allData = await response.json();
                updateCounts(allData);
                filterHomeData();
                fetchVisitsTodayCount();
                showMessage('Data fetched successfully!', 'success');

            } catch (error) {
                console.error('Error fetching data:', error);
                showMessage(`Failed to fetch data: ${error.message}`, 'error');
                homeDataResultsDiv.innerHTML = '<p class="text-center text-gray-500 py-4">Could not load data. Check console for details.</p>';
                updateCounts([]);
            } finally {
                globalLoadingIndicator.classList.add('hidden');
                homeFetchDataBtn.disabled = false;
                homeRefreshSpinner.classList.add('hidden');
            }
        }

        /**
         * Handles the "Check-in Family" action.
         * @param {string} familyId - The member_id (family ID) of the primary member.
         */
        async function checkInFamily(familyId) {
            const numPeopleStr = prompt("Enter the number of people checking in for this family:");
            const numPeople = parseInt(numPeopleStr);

            if (isNaN(numPeople) || numPeople <= 0) {
                showMessage("Invalid number of people. Please enter a positive number.", "error");
                return;
            }

            globalLoadingIndicator.classList.remove('hidden');

            try {
                const primaryMember = allData.find(m => m.member_id === familyId && m.primary_member === true);

                if (!primaryMember) {
                    showMessage(`Primary member not found for family ID: ${familyId}. Cannot record visits.`, "error");
                    return;
                }
				let successfulVisits = 0;
                let failedVisits = 0;

                for (let i = 0; i < numPeople; i++) {
                    const now = new Date();
                    const formattedDateTime = `${now.getFullYear()}-${(now.getMonth() + 1).toString().padStart(2, '0')}-${now.getDate().toString().padStart(2, '0')} ${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;

                    const visitData = {
                        member_id: primaryMember.member_id,
                        name: primaryMember.name,
                        last_name: primaryMember.last_name,
                        visit_datetime: formattedDateTime
                    };

                    const response = await apiFetch('/add_visit', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(visitData)
                    });

                    if (response.ok) {
                        successfulVisits++;
                    } else {
                        failedVisits++;
                        const errorData = await response.json();
                        console.error(`Error recording visit ${i + 1} for ${primaryMember.name} ${primaryMember.last_name}:`, errorData);
                    }
                }

                if (successfulVisits === numPeople) {
                    showMessage(`${successfulVisits} visits recorded successfully for ${primaryMember.name} ${primaryMember.last_name}!`, "success");
                } else if (successfulVisits > 0) {
                    showMessage(`${successfulVisits} out of ${numPeople} visits recorded for ${primaryMember.name} ${primaryMember.last_name}. ${failedVisits} failed.`, "warning");
                } else {
                    showMessage(`Failed to record any visits for ${primaryMember.name} ${primaryMember.last_name}.`, "error");
                }

                await fetchAllData();
				showView('homeView');

            } catch (error) {
                console.error('Error during family check-in:', error);
                showMessage(`An error occurred during check-in: ${error.message}`, "error");
            } finally {
                globalLoadingIndicator.classList.add('hidden');
            }
        }
        
        // --- NEW: Function to trigger renewal email sending ---
        /**
         * Calls the backend to initiate the sending of renewal emails.
         */
        async function sendRenewalEmails() {
            if (!confirm("Are you sure you want to run the monthly renewal email process? This will send emails to all members expiring this month who have not yet received a notice.")) {
                return;
            }

            showLoadingIndicator();
            try {
                const response = await apiFetch('/send_renewal_emails', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });

                const result = await response.json();

                if (!response.ok) {
                    throw new Error(result.error || `HTTP error! Status: ${response.status}`);
                }

                showMessage(result.message, 'success');
                await fetchAllData(); // Refresh the data to show the new mail icons

            } catch (error) {
                console.error('Error sending renewal emails:', error);
                showMessage(`Failed to send renewal emails: ${error.message}`, 'error');
            } finally {
                hideLoadingIndicator();
            }
        }


        // Home View Event Listeners
        homeFetchDataBtn.addEventListener('click', fetchAllData);
        homeLastNameSearchInput.addEventListener('input', filterHomeData);
        showInactiveToggle.addEventListener('change', filterHomeData);
        homeAddRecordBtn.addEventListener('click', () => {
            showView('addRecordView');
            resetAddRecordForm();
        });
        // --- NEW: Add event listener for the new button ---
        homeSendEmailsBtn.addEventListener('click', sendRenewalEmails);
        
        // --- Generate Member Report Functionality ---
        homeGenerateReportBtn.addEventListener('click', () => {
            if (!allData || allData.length === 0) {
                showMessage('No data available to generate a report. Please fetch data first.', 'info');
                return;
            }

            const reportHeaders = [
                "Member ID", "First Name", "Last Name", "Phone", "Gender", "Birthday",
                "Primary Member", "Secondary Member", "Address", "City", "State",
                "Zip Code", "Email", "Founding Family", "Membership Start Date",
                "Membership Expires", "Active"
            ];

            const keyMap = {
                member_id: "Member ID",
                name: "First Name",
                last_name: "Last Name",
                phone: "Phone",
                gender: "Gender",
                birthday: "Birthday",
                primary_member: "Primary Member",
                secondary_member: "Secondary Member",
                address: "Address",
                city: "City",
                state: "State",
                zip_code: "Zip Code",
                email: "Email",
                founding_family: "Founding Family",
                mem_start_date: "Membership Start Date",
                membership_expires: "Membership Expires",
                active_flag: "Active"
            };

            let csvContent = reportHeaders.map(header => `"${header}"`).join(',') + '\n';

            allData.forEach(row => {
                const rowValues = reportHeaders.map(header => {
                    const originalKey = Object.keys(keyMap).find(key => keyMap[key] === header);
                    let value = row[originalKey];

                    if (originalKey === 'founding_family' || originalKey === 'primary_member' || originalKey === 'secondary_member' || originalKey === 'active_flag') {
                        value = value ? 'Yes' : 'No';
                    } else if (originalKey === 'gender') {
                        value = value === true ? 'Male' : (value === false ? 'Female' : 'N/A');
                    } else if (originalKey === 'birthday' || originalKey === 'mem_start_date' || originalKey === 'membership_expires') {
                        const dateObj = parseDateRobustly(value);
                        value = formatDate(dateObj);
                    } else if (originalKey === 'phone') {
                        value = formatPhoneNumber(value);
                    }
                    
                    if (value === null || value === undefined || String(value).trim() === '') {
                        value = 'N/A';
                    }

                    const escapedValue = String(value).replace(/"/g, '""');
                    return `"${escapedValue}"`;
                });
                csvContent += rowValues.join(',') + '\n';
            });

            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const link = document.createElement('a');
            if (link.download !== undefined) {
                const url = URL.createObjectURL(blob);
                link.setAttribute('href', url);
                link.setAttribute('download', 'Member_Report.csv');
                link.style.visibility = 'hidden';
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                showMessage('Member report generated and downloaded successfully!', 'success');
            } else {
                showMessage('Your browser does not support downloading files directly. Please copy the data manually.', 'error');
            }
        });


        // --- Add Record View Logic ---
        const addRecordForm = document.getElementById('addRecordForm');
        const addNameInput = document.getElementById('addName');
        const addLastNameInput = document.getElementById('addLastName');
        const addEmailInput = document.getElementById('addEmail');
        const addPhoneInput = document.getElementById('addPhone');
        const addAddressInput = document.getElementById('addAddress');
        const addCityInput = document.getElementById('addCity');
        const addStateInput = document.getElementById('addState');
        const addZipCodeInput = document.getElementById('addZipCode');
        const addBirthdayInput = document.getElementById('addBirthday');
        const addGenderSelect = document.getElementById('addGender');
        const addFoundingFamilyCheckbox = document.getElementById('addFoundingFamily');
        const addRecordHeader = document.getElementById('addRecordHeader');
        const addFamilyMembersBtn = document.getElementById('addFamilyMembersBtn');
        const addRecordCancelBtn = document.getElementById('addRecordCancelBtn');

        function generatePreviewMemberId() {
            const firstName = addNameInput.value.trim();
            const lastName = addLastNameInput.value.trim();

            if (!firstName || !lastName) {
                return '';
            }

            const lastNamePart = (lastName + '   ').slice(0, 3);
            const firstNamePart = (firstName + '  ').slice(0, 2);

            const part1 = lastNamePart.charAt(0).toUpperCase() + lastNamePart.slice(1).toLowerCase();
            const part2 = firstNamePart.charAt(0).toUpperCase() + firstNamePart.slice(1).toLowerCase();
            
            return part1 + part2;
        }

        function updateAddRecordHeaderWithMemberId() {
            const previewId = generatePreviewMemberId();
            if (previewId) {
                addRecordHeader.innerHTML = `<span class="bg-clip-text text-transparent bg-gradient-to-r from-purple-800 to-indigo-900">Add New Family Member: ${previewId}</span>`;
            } else {
                addRecordHeader.innerHTML = `<span class="bg-clip-text text-transparent bg-gradient-to-r from-purple-800 to-indigo-900">Add New Member Record</span>`;
            }
        }

        function resetAddRecordForm() {
            addRecordForm.reset();
            updateAddRecordHeaderWithMemberId();
            addFamilyMembersBtn.classList.add('hidden');
        }

        addNameInput.addEventListener('input', updateAddRecordHeaderWithMemberId);
        addLastNameInput.addEventListener('input', updateAddRecordHeaderWithMemberId);

		addRecordForm.addEventListener('submit', async (event) => {
            event.preventDefault();

            globalLoadingIndicator.classList.remove('hidden');
            addRecordForm.querySelectorAll('input, select, button').forEach(el => el.disabled = true);

            const name = addNameInput.value.trim();
            const lastName = addLastNameInput.value.trim();
            const email = addEmailInput.value.trim();
            const phone = addPhoneInput.value.trim();
            const address = addAddressInput.value.trim();
            const city = addCityInput.value.trim();
            const state = addStateInput.value.trim();
            const zipCode = addZipCodeInput.value.trim();
            const birthday = addBirthdayInput.value;
            const gender = addGenderSelect.value;
            const foundingFamily = addFoundingFamilyCheckbox.checked;
            
            const primaryMember = true;
            const secondaryMember = false;

            if (!name || !lastName) {
                showMessage('Please fill in all required fields (First Name, Last Name).', 'error');
                globalLoadingIndicator.classList.add('hidden');
                addRecordForm.querySelectorAll('input, select, button').forEach(el => el.disabled = false);
                return;
            }

            let genderValue = null;
            if (gender === 'true') {
                genderValue = true;
            } else if (gender === 'false') {
                genderValue = false;
            }

            const recordData = {
                name: name,
                last_name: lastName,
                email: email || null,
                phone: phone || null,
                address: address || null,
                city: city || null,
                state: state || null,
                zip_code: zipCode || null,
                birthday: birthday || null,
                gender: genderValue,
                founding_family: foundingFamily,
                primary_member: primaryMember,
                secondary_member: secondaryMember
            };
            
            try {
					const response = await apiFetch('/add_record', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(recordData)
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    console.error('Add Primary Record Backend Error Response:', errorData);
                    throw new Error(`HTTP error! Status: ${response.status}. Details: ${errorData.error || 'Unknown error'}`);
                }

                const result = await response.json();
                showMessage(result.message || 'Record added successfully!', 'success');
                
                // --- MODIFIED WORKFLOW ---
                // Set the current family ID from the response
                currentFamilyId = result.member_id;
                
                // Refresh the master data list in the background
                await fetchAllData();

                // Reset the form for the next time it's used
                resetAddRecordForm();

                // Switch to the family details view
                showView('familyDetailsView');
                
                // Render the details for the newly created family
                await renderFamilyDetailsView();
                // --- END MODIFICATION ---

            } catch (error) {
                console.error('Error adding record:', error);
                showMessage(`Failed to add record: ${error.message}`, 'error');
            } finally {
                globalLoadingIndicator.classList.add('hidden');
                addRecordForm.querySelectorAll('input, select, button').forEach(el => el.disabled = false);
            }
        });
		
        addFamilyMembersBtn.addEventListener('click', () => {
            if (currentFamilyId) {
                showView('manageSecondaryMembersView');
                document.getElementById('manageSecondaryFamilyIdDisplay').textContent = currentFamilyId;
                fetchManageSecondaryMembers();
                resetManageSecondaryAddForm();
            } else {
                showMessage('Please add a primary member first.', 'error');
            }
        });

        addRecordCancelBtn.addEventListener('click', () => {
            showView('homeView');
            resetAddRecordForm();
        });

        // --- Family Details View Logic ---
        const displayMemberId = document.getElementById('displayMemberId');
        const familyAddress = document.getElementById('familyAddress');
        const familyCityStateZip = document.getElementById('familyCityStateZip');
        const familyMembershipExpires = document.getElementById('familyMembershipExpires');
        const familyEmail = document.getElementById('familyEmail');
        const updateMembershipContainer = document.getElementById('updateMembershipContainer');
        const familyMemStartDateDisplay = document.getElementById('familyMemStartDateDisplay');
        const updateMembershipBtn = document.getElementById('updateMembershipBtn');
        const familyDetailsManageSecondaryMembersBtn = document.getElementById('familyDetailsManageSecondaryMembersBtn');
        const familyDetailsCloseBtn = document.getElementById('familyDetailsCloseBtn');
        const individualMembersList = document.getElementById('individualMembersList');

        let primaryMemberRecord = null;

        /**
         * Renders the Family Details view based on the selected family ID.
         */
        async function renderFamilyDetailsView() {
            showView('familyDetailsView');
            globalLoadingIndicator.classList.remove('hidden');
            familyDetailsContent.classList.add('hidden');
            messageBox.classList.add('hidden');

            if (!currentFamilyId) {
                showMessage('No family selected. Please return to the main page and double-click a record.', 'error');
                globalLoadingIndicator.classList.add('hidden');
                return;
            }

            try {
                const familyMembers = allData.filter(member => member.member_id === currentFamilyId);

                if (familyMembers.length > 0) {
                    primaryMemberRecord = familyMembers.find(m => m.primary_member === true) || familyMembers[0];
                    
                    const memStartDateObj = parseDateRobustly(primaryMemberRecord.mem_start_date);
                    const membershipExpiresObj = parseDateRobustly(primaryMemberRecord.membership_expires);

                    displayMemberId.textContent = currentFamilyId;
                    familyAddress.textContent = primaryMemberRecord.address || 'N/A';
                    
                    const city = primaryMemberRecord.city || '';
                    const state = primaryMemberRecord.state || '';
                    const zip = primaryMemberRecord.zip_code || '';
                    familyCityStateZip.textContent = `${city}${city && state ? ', ' : ''}${state} ${zip}`.trim() || 'N/A';
                    
                    familyEmail.textContent = primaryMemberRecord.email || 'N/A';

                    if (primaryMemberRecord.founding_family) {
                        familyMembershipExpires.textContent = 'Founding Family';
                        updateMembershipContainer.style.display = 'none';
                    } else {
                        familyMembershipExpires.textContent = formatDate(membershipExpiresObj);
                        familyMemStartDateDisplay.textContent = formatDate(memStartDateObj);
                        updateMembershipContainer.style.display = 'block';
                    }

                    individualMembersList.innerHTML = '';
                    familyMembers.sort((a, b) => {
                        if (a.primary_member && !b.primary_member) return -1;
                        if (!a.primary_member && b.primary_member) return 1;
                        return (a.last_name || '').localeCompare(b.last_name) || (a.name || '').localeCompare(b.name);
                    });

                    familyMembers.forEach(member => {
                        let memberCardHtml = `
                            <div class="member-card">
                                <div class="member-card-header">
                                    ${member.name || 'N/A'} ${member.last_name || 'N/A'}
                                    ${member.primary_member ? '<span class="ml-2 text-xs bg-indigo-200 text-indigo-800 px-2 py-1 rounded-full">Primary</span>' : ''}
                                    ${member.secondary_member ? '<span class="ml-2 text-xs bg-purple-200 text-purple-800 px-2 py-1 rounded-full">Secondary</span>' : ''}
                                </div>
                                <div class="member-card-details">
                                    <div class="member-card-detail-item"><span class="member-card-detail-label">Birthday:</span><span class="member-card-detail-value">${formatDate(parseDateRobustly(member.birthday))}</span></div>
                                    <div class="member-card-detail-item"><span class="member-card-detail-label">Gender:</span><span class="member-card-detail-value">${member.gender === true ? 'Male' : (member.gender === false ? 'Female' : 'N/A')}</span></div>
                                    <div class="member-card-detail-item"><span class="member-card-detail-label">Phone:</span><span class="member-card-detail-value">${formatPhoneNumber(member.phone)}</span></div>
                                </div>
                                <div class="action-buttons">
                                    <button onclick="editIndividualMember('${member.member_id}', '${member.name}', '${member.last_name}')" class="action-button btn-primary text-sm">View/Edit Member</button>
                                    <button onclick="showAddVisitView('${member.member_id}', '${member.name}', '${member.last_name}')" class="action-button btn-primary text-sm bg-blue-500 hover:bg-blue-600">Add Visit</button>
                                    <button onclick="showMemberVisits('${member.member_id}', '${member.name}', '${member.last_name}', '${primaryMemberRecord.mem_start_date}')" class="action-button btn-secondary text-sm">View Visits</button>
                                </div>
                            </div>`;
                        individualMembersList.insertAdjacentHTML('beforeend', memberCardHtml);
                    });
                    familyDetailsContent.classList.remove('hidden');
                } else {
                    showMessage(`No members found for family ID: ${currentFamilyId}.`, 'error');
                }

            } catch (error) {
                console.error('Family Details View: Error rendering family data:', error);
                showMessage(`Failed to load family data: ${error.message}`, 'error');
            } finally {
                globalLoadingIndicator.classList.add('hidden');
            }
        }

        // Family Details View Event Listeners
        updateMembershipBtn.addEventListener('click', async () => {
            if (!primaryMemberRecord) {
                showMessage('Error: Primary member record not found for updating membership.', 'error');
                return;
            }

            globalLoadingIndicator.classList.remove('hidden');
            updateMembershipBtn.disabled = true;

            try {
                // When the button is clicked, always use the current date as the start date.
                const newMemStartDateISO = new Date().toISOString().split('T')[0];

                const updatedData = {
                    mem_start_date: newMemStartDateISO,
                    active_flag: true,
                    is_primary: true // Ensure backend knows this is a primary member update
                };

                const response = await apiFetch(`/update_record/${primaryMemberRecord.member_id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(updatedData)
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(`HTTP error! Status: ${response.status}. Details: ${errorData.error || 'Unknown error'}`);
                }

                const result = await response.json();
                showMessage(result.message || 'Membership dates and status updated successfully!', 'success');
                
                await fetchAllData();
                renderFamilyDetailsView();

            } catch (error) {
                console.error('Error updating membership dates:', error);
                showMessage(`Failed to update membership: ${error.message}`, 'error');
            } finally {
                globalLoadingIndicator.classList.add('hidden');
                updateMembershipBtn.disabled = false;
            }
        });

        familyDetailsManageSecondaryMembersBtn.addEventListener('click', () => {
            if (currentFamilyId) {
                showView('manageSecondaryMembersView');
                document.getElementById('manageSecondaryFamilyIdDisplay').textContent = currentFamilyId;
                fetchManageSecondaryMembers();
                resetManageSecondaryAddForm();
            } else {
                showMessage('No family selected to manage secondary members.', 'error');
            }
        });

        familyDetailsCloseBtn.addEventListener('click', () => {
            showView('homeView');
            currentFamilyId = null;
        });

        // --- Record Details View Logic (for individual member editing) ---
        const recordDetailForm = document.getElementById('recordDetailForm');
        const recordDetailsMemberIdDisplay = document.getElementById('recordDetailsMemberIdDisplay');
        const recordDetailsNameInput = document.getElementById('recordDetailsName');
        const recordDetailsLastNameInput = document.getElementById('recordDetailsLastName');
        const recordDetailsEmailInput = document.getElementById('recordDetailsEmail');
        const recordDetailsPhoneInput = document.getElementById('recordDetailsPhone');
        const recordDetailsAddressInput = document.getElementById('recordDetailsAddress');
        const recordDetailsCityInput = document.getElementById('recordDetailsCity');
        const recordDetailsStateInput = document.getElementById('recordDetailsState');
        const recordDetailsZipCodeInput = document.getElementById('recordDetailsZipCode');
        const recordDetailsBirthdayInput = document.getElementById('recordDetailsBirthday');
        const recordDetailsGenderSelect = document.getElementById('recordDetailsGender');
        const recordDetailsFoundingFamilyCheckbox = document.getElementById('recordDetailsFoundingFamily');
        const recordDetailsPrimaryMemberCheckbox = document.getElementById('recordDetailsPrimaryMember');
        const recordDetailsSecondaryMemberCheckbox = document.getElementById('recordDetailsSecondaryMember');
        const recordDetailsMemStartDateInput = document.getElementById('recordDetailsMemStartDate');
        const recordDetailsMembershipExpiresContainer = document.getElementById('recordDetailsMembershipExpiresContainer');
        const recordDetailsMembershipExpiresInput = document.getElementById('recordDetailsMembershipExpires');
        const recordDetailsActiveFlagCheckbox = document.getElementById('recordDetailsActiveFlag');
        const recordDetailsDeleteRecordBtn = document.getElementById('recordDetailsDeleteRecordBtn');
        const recordDetailsCloseBtn = document.getElementById('recordDetailsCloseBtn');

        let currentRecordDetailsFamilyId = null;
        let currentRecordDetailsName = null;
        let currentRecordDetailsLastName = null;
        let currentRecordDetailsIsPrimary = false;

        async function editIndividualMember(familyId, name, lastName) {
            showView('recordDetailsView');
            globalLoadingIndicator.classList.remove('hidden');
            recordDetailForm.querySelectorAll('input, select, button').forEach(el => el.disabled = true);
            messageBox.classList.add('hidden');

            currentRecordDetailsFamilyId = familyId;
            currentRecordDetailsName = name;
            currentRecordDetailsLastName = lastName;

            try {
                const record = allData.find(item => item.member_id === familyId && item.name === name && item.last_name === lastName);

                if (record) {
                    currentRecordDetailsIsPrimary = record.primary_member;

                    recordDetailsMemberIdDisplay.textContent = `${familyId} (${name} ${lastName})`;
                    recordDetailsNameInput.value = record.name || '';
                    recordDetailsLastNameInput.value = record.last_name || '';
                    recordDetailsPhoneInput.value = record.phone || '';
                    recordDetailsBirthdayInput.value = record.birthday ? formatDateForInput(parseDateRobustly(record.birthday)) : '';
                    recordDetailsGenderSelect.value = record.gender !== null ? String(record.gender) : '';
                    recordDetailsEmailInput.value = record.email || '';
                    recordDetailsAddressInput.value = record.address || '';
                    recordDetailsCityInput.value = record.city || '';
                    recordDetailsStateInput.value = record.state || '';
                    recordDetailsZipCodeInput.value = record.zip_code || '';
                    recordDetailsFoundingFamilyCheckbox.checked = record.founding_family || false;
                    recordDetailsMemStartDateInput.value = record.mem_start_date ? formatDateForInput(parseDateRobustly(record.mem_start_date)) : '';
                    recordDetailsMembershipExpiresInput.value = record.membership_expires ? formatDateForInput(parseDateRobustly(record.membership_expires)) : '';
                    recordDetailsActiveFlagCheckbox.checked = record.active_flag || false;
                    recordDetailsPrimaryMemberCheckbox.checked = record.primary_member || false;
                    recordDetailsSecondaryMemberCheckbox.checked = record.secondary_member || false;

                    const isPrimary = record.primary_member;
                    recordDetailsNameInput.disabled = false;
                    recordDetailsLastNameInput.disabled = false;
                    recordDetailsPhoneInput.disabled = false;
                    recordDetailsBirthdayInput.disabled = false;
                    recordDetailsGenderSelect.disabled = false;
                    recordDetailsEmailInput.disabled = !isPrimary;
                    recordDetailsAddressInput.disabled = !isPrimary;
                    recordDetailsCityInput.disabled = !isPrimary;
                    recordDetailsStateInput.disabled = !isPrimary;
                    recordDetailsZipCodeInput.disabled = !isPrimary;
                    recordDetailsFoundingFamilyCheckbox.disabled = !isPrimary;
                    recordDetailsMemStartDateInput.disabled = !isPrimary;
                    
                    // Allow editing expires date for primary, non-founding members
                    recordDetailsMembershipExpiresInput.disabled = true; // Always disabled

                    recordDetailsActiveFlagCheckbox.disabled = !isPrimary || record.founding_family;

                    if (record.founding_family) {
                        recordDetailsMembershipExpiresContainer.style.display = 'none';
                    } else {
                        recordDetailsMembershipExpiresContainer.style.display = 'block';
                    }
					// Toggle delete button visibility by role
					if (isPrimary) {
						// Primary: hide the delete button entirely
						recordDetailsDeleteRecordBtn.classList.add('hidden');   // Tailwind: display: none
						recordDetailsDeleteRecordBtn.disabled = true;
						recordDetailsDeleteRecordBtn.title = 'Primary members cannot be deleted.';
					} else {
						// Secondary: show & enable the button
						recordDetailsDeleteRecordBtn.classList.remove('hidden');
						recordDetailsDeleteRecordBtn.disabled = false;
						recordDetailsDeleteRecordBtn.title = '';
					}
					recordDetailForm.querySelector('button[type="submit"]').disabled = false;
                    // recordDetailsDeleteRecordBtn.disabled = false;
                    recordDetailsCloseBtn.disabled = false;
                } else {
                    showMessage('Record not found for the given ID, Name, and Last Name.', 'error');
                }
            } catch (error) {
                console.error('Error preparing record details view:', error);
                showMessage(`Failed to load record: ${error.message}`, 'error');
            } finally {
                globalLoadingIndicator.classList.add('hidden');
                recordDetailsCloseBtn.disabled = false;
            }
        }

        recordDetailForm.addEventListener('submit', async (event) => {
            event.preventDefault();

            if (!currentRecordDetailsFamilyId) {
                showMessage('No record selected for update.', 'error');
                return;
            }

            globalLoadingIndicator.classList.remove('hidden');
            recordDetailForm.querySelectorAll('input, select, button').forEach(el => el.disabled = true);

            const recordData = {
                name: recordDetailsNameInput.value.trim(),
                last_name: recordDetailsLastNameInput.value.trim(),
                phone: recordDetailsPhoneInput.value.trim() || null,
                birthday: recordDetailsBirthdayInput.value || null,
                gender: recordDetailsGenderSelect.value !== '' ? (recordDetailsGenderSelect.value === 'true') : null,
                original_name: currentRecordDetailsName,
                original_last_name: currentRecordDetailsLastName,
                is_primary: currentRecordDetailsIsPrimary
            };

            if (currentRecordDetailsIsPrimary) {
                recordData.email = recordDetailsEmailInput.value.trim() || null;
                recordData.address = recordDetailsAddressInput.value.trim() || null;
                recordData.city = recordDetailsCityInput.value.trim() || null;
                recordData.state = recordDetailsStateInput.value.trim() || null;
                recordData.zip_code = recordDetailsZipCodeInput.value.trim() || null;
                recordData.founding_family = recordDetailsFoundingFamilyCheckbox.checked;
                recordData.mem_start_date = recordDetailsMemStartDateInput.value || null;
                recordData.active_flag = recordDetailsActiveFlagCheckbox.checked;
            }

            try {
                const response = await apiFetch(`/update_record/${currentRecordDetailsFamilyId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(recordData)
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(`HTTP error! Status: ${response.status}. Details: ${errorData.error || 'Unknown error'}`);
                }

                const result = await response.json();
                showMessage(result.message || 'Record updated successfully!', 'success');
                
                await fetchAllData(); 
                showView('familyDetailsView');
                await renderFamilyDetailsView();

            } catch (error) {
                console.error('Error updating record:', error);
                showMessage(`Failed to update record: ${error.message}`, 'error');
            } finally {
                globalLoadingIndicator.classList.add('hidden');
                recordDetailForm.querySelectorAll('input, select, button').forEach(el => el.disabled = false);
            }
        });

        recordDetailsDeleteRecordBtn.addEventListener('click', async () => {
            if (!currentRecordDetailsFamilyId) return;

            let confirmMessage = currentRecordDetailsIsPrimary
                ? `Are you sure you want to delete the PRIMARY member and ALL associated family members for Family ID: ${currentRecordDetailsFamilyId}? This action cannot be undone.`
                : `Are you sure you want to delete ${currentRecordDetailsName} ${currentRecordDetailsLastName} from Family ID: ${currentRecordDetailsFamilyId}?`;
            
            if (confirm(confirmMessage)) {
                globalLoadingIndicator.classList.remove('hidden');
                const requestBody = currentRecordDetailsIsPrimary ? {} : { name: currentRecordDetailsName, last_name: currentRecordDetailsLastName };
                try {
                    const response = await apiFetch(`/delete_record/${currentRecordDetailsFamilyId}`, {
                        method: 'DELETE',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(requestBody)
                    });

                    if (!response.ok) {
                        const errorData = await response.json();
                        throw new Error(`HTTP error! Status: ${response.status}. Details: ${errorData.error || 'Unknown error'}`);
                    }

                    const result = await response.json();
                    showMessage(result.message || 'Record deleted successfully!', 'success');
                    
                    await fetchAllData();
                    if (currentRecordDetailsIsPrimary) {
                        showView('homeView');
                        currentFamilyId = null;
                    } else {
                        showView('familyDetailsView');
                        await renderFamilyDetailsView();
                    }
                } catch (error) {
                    console.error('Error deleting record:', error);
                    showMessage(`Failed to delete record: ${error.message}`, 'error');
                } finally {
                    globalLoadingIndicator.classList.add('hidden');
                }
            }
        });

        recordDetailsCloseBtn.addEventListener('click', () => {
            showView('familyDetailsView');
        });

        // --- Manage Secondary Members View Logic ---
        const manageSecondaryFamilyIdDisplay = document.getElementById('manageSecondaryFamilyIdDisplay');
        const manageSecondaryMembersTableBody = document.getElementById('manageSecondaryMembersTableBody');
        const manageSecondaryAddForm = document.getElementById('manageSecondaryAddForm');
        const manageSecondaryCloseBtn = document.getElementById('manageSecondaryCloseBtn');

        async function fetchManageSecondaryMembers() {
            if (!currentFamilyId) return;
            globalLoadingIndicator.classList.remove('hidden');

            try {
                const familyMembers = allData.filter(member => member.member_id === currentFamilyId);
                if (familyMembers.length === 0) {
                    manageSecondaryMembersTableBody.innerHTML = '<tr><td colspan="4" class="text-center py-4 text-gray-500">No family members found.</td></tr>';
                    return;
                }

                familyMembers.sort((a, b) => {
                    if (a.primary_member && !b.primary_member) return -1;
                    if (!a.primary_member && b.primary_member) return 1;
                    return (a.last_name || '').localeCompare(b.last_name) || (a.name || '').localeCompare(b.name);
                });

                let tableHtml = '';
                familyMembers.forEach(member => {
                    const role = member.primary_member ? 'Primary' : 'Secondary';
                    tableHtml += `
                        <tr>
                            <td class="px-6 py-4 whitespace-nowrap">${member.name || 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap">${member.last_name || 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap">${role}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-center">
                                ${!member.primary_member ? `<button type="button" onclick="deleteSecondaryMember('${member.member_id}', '${member.name}', '${member.last_name}')" class="delete-secondary-member-btn action-button btn-delete text-xs px-3 py-1">Delete</button>` : 'N/A'}
                            </td>
                        </tr>`;
                });
                manageSecondaryMembersTableBody.innerHTML = tableHtml;
            } catch (error) {
                console.error('Error rendering secondary members list:', error);
                showMessage('Failed to display family members.', 'error');
            } finally {
                globalLoadingIndicator.classList.add('hidden');
            }
        }

        async function deleteSecondaryMember(memberId, name, lastName) {
            if (confirm(`Are you sure you want to delete ${name} ${lastName} from this family?`)) {
                globalLoadingIndicator.classList.remove('hidden');
                try {
                    const response = await apiFetch(`/delete_record/${memberId}`, {
                        method: 'DELETE',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: name, last_name: lastName })
                    });
                    if (!response.ok) {
                        const errorData = await response.json();
                        throw new Error(`HTTP error! Status: ${response.status}. Details: ${errorData.error || 'Unknown error'}`);
                    }
                    const result = await response.json();
                    showMessage(result.message || 'Secondary member deleted successfully!', 'success');
                    await fetchAllData();
                    await fetchManageSecondaryMembers();
                } catch (error) {
                    console.error('Error deleting secondary member:', error);
                    showMessage(`Failed to delete secondary member: ${error.message}`, 'error');
                } finally {
                    globalLoadingIndicator.classList.add('hidden');
                }
            }
        }

        function resetManageSecondaryAddForm() {
            manageSecondaryAddForm.reset();
        }

        manageSecondaryAddForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (!currentFamilyId) return;

            globalLoadingIndicator.classList.remove('hidden');
            const name = document.getElementById('manageSecondaryName').value.trim();
            const lastName = document.getElementById('manageSecondaryLastName').value.trim();
            if (!name || !lastName) {
                showMessage('Please fill in First Name and Last Name.', 'error');
                globalLoadingIndicator.classList.add('hidden');
                return;
            }

            const gender = document.getElementById('manageSecondaryGender').value;
            let genderValue = gender !== '' ? (gender === 'true') : null;

            const recordData = {
                primary_member_id: currentFamilyId,
                name: name,
                last_name: lastName,
                phone: document.getElementById('manageSecondaryPhone').value.trim() || null,
                birthday: document.getElementById('manageSecondaryBirthday').value || null,
                gender: genderValue,
            };
            try {
                const response = await apiFetch('/add_secondary_member', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(recordData)
                });
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(`HTTP error! Status: ${response.status}. Details: ${errorData.error || 'Unknown error'}`);
                }
                const result = await response.json();
                showMessage(result.message || 'Secondary member added successfully!', 'success');
                resetManageSecondaryAddForm();
                await fetchAllData();
                fetchManageSecondaryMembers();
            } catch (error) {
                console.error('Error adding secondary member:', error);
                showMessage(`Failed to add secondary member: ${error.message}`, 'error');
            } finally {
                globalLoadingIndicator.classList.add('hidden');
            }
        });

        manageSecondaryCloseBtn.addEventListener('click', () => {
            showView('familyDetailsView');
            renderFamilyDetailsView(); // Re-render the family details view
        });

        // --- Add Visit View Logic & Member Visits View Logic ---
        const addVisitForm = document.getElementById('addVisitForm');
        const addVisitMemberIdInput = document.getElementById('addVisitMemberId');
        const addVisitNameInput = document.getElementById('addVisitName');
        const addVisitLastNameInput = document.getElementById('addVisitLastName');
        const addVisitDateTimeInput = document.getElementById('addVisitDateTime');
        const addVisitCancelBtn = document.getElementById('addVisitCancelBtn');
        const memberVisitsDisplayName = document.getElementById('memberVisitsDisplayName');
        const memberVisitsDisplayId = document.getElementById('memberVisitsDisplayId');
        const visitsSinceMembershipCount = document.getElementById('visitsSinceMembershipCount');
        const currentMonthYearSpan = document.getElementById('currentMonthYear');
        const prevMonthBtn = document.getElementById('prevMonthBtn');
        const nextMonthBtn = document.getElementById('nextMonthBtn');
        const calendarDaysDiv = document.getElementById('calendarDays');
        const allOtherVisitsContainer = document.getElementById('allOtherVisitsContainer');
        const memberVisitsCloseBtn = document.getElementById('memberVisitsCloseBtn');
        
        function showAddVisitView(memberId, name, lastName) {
            showView('addVisitView');
            currentAddVisitMemberId = memberId;
            currentAddVisitName = name;
            currentAddVisitLastName = lastName;
            addVisitMemberIdInput.value = memberId;
            addVisitNameInput.value = name;
            addVisitLastNameInput.value = lastName;
            addVisitDateTimeInput.value = formatDateTimeLocalForInput(new Date());
        }

        addVisitForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            globalLoadingIndicator.classList.remove('hidden');
            const localDate = new Date(addVisitDateTimeInput.value);
            const formattedDateTime = `${localDate.getFullYear()}-${(localDate.getMonth() + 1).toString().padStart(2, '0')}-${localDate.getDate().toString().padStart(2, '0')} ${localDate.getHours().toString().padStart(2, '0')}:${localDate.getMinutes().toString().padStart(2, '0')}:${localDate.getSeconds().toString().padStart(2, '0')}`;
            const visitData = {
                member_id: currentAddVisitMemberId,
                name: currentAddVisitName,
                last_name: currentAddVisitLastName,
                visit_datetime: formattedDateTime
            };
            try {
                const response = await apiFetch('/add_visit', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(visitData)
                });
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(`HTTP error! Status: ${response.status}. Details: ${errorData.error || 'Unknown error'}`);
                }
                const result = await response.json();
                showMessage(result.message || 'Visit recorded successfully!', 'success');
                await fetchAllData();
                showView('familyDetailsView');
            } catch (error) {
                console.error('Error recording visit:', error);
                showMessage(`Failed to record visit: ${error.message}`, 'error');
            } finally {
                globalLoadingIndicator.classList.add('hidden');
            }
        });
        
        addVisitCancelBtn.addEventListener('click', () => showView('familyDetailsView'));

        function renderCalendar(year, month, visitedDates) {
            const today = new Date();
            const firstDayOfMonth = new Date(year, month, 1);
            const daysInMonth = new Date(year, month + 1, 0).getDate();
            const firstWeekday = firstDayOfMonth.getDay();

            currentMonthYearSpan.textContent = `${firstDayOfMonth.toLocaleString('en-US', { month: 'long', year: 'numeric' })}`;
            calendarDaysDiv.innerHTML = '';

            const isVisited = (day) => {
                const checkDate = new Date(year, month, day);
                return visitedDates.some(vDate => vDate.getFullYear() === checkDate.getFullYear() && vDate.getMonth() === checkDate.getMonth() && vDate.getDate() === checkDate.getDate());
            };

            for (let i = 0; i < firstWeekday; i++) {
                calendarDaysDiv.insertAdjacentHTML('beforeend', '<div class="calendar-day empty"></div>');
            }

            for (let day = 1; day <= daysInMonth; day++) {
                const dayDiv = document.createElement('div');
                dayDiv.classList.add('calendar-day');
                dayDiv.textContent = day;
                const calendarDay = new Date(year, month, day);
                if (calendarDay.toDateString() === today.toDateString()) {
                    dayDiv.classList.add('current-day');
                }
                if (isVisited(day)) {
                    dayDiv.classList.add('visited-day');
                }
                calendarDaysDiv.appendChild(dayDiv);
            }
        }

        async function showMemberVisits(memberId, name, lastName, memStartDateISO) {
            showView('memberVisitsView');
            globalLoadingIndicator.classList.remove('hidden');
            memberVisitsDisplayName.textContent = `${name} ${lastName}`;
            memberVisitsDisplayId.textContent = memberId;
            visitsSinceMembershipCount.textContent = 'Loading...';
            allOtherVisitsContainer.innerHTML = '<p class="text-gray-600 text-center py-4">Loading visits...</p>';
            
            currentVisitsMemStartDate = parseDateRobustly(memStartDateISO);
            currentCalendarDate = new Date();

            try {
                const response = await apiFetch(`/visits/${encodeURIComponent(memberId)}/${encodeURIComponent(name)}/${encodeURIComponent(lastName)}`);
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(`HTTP error! Status: ${response.status}. Details: ${errorData.error || 'Unknown error'}`);
                }
                const visits = await response.json();
                allMemberVisitedDates = visits.map(v => new Date(v));
                
                visitsSinceMembershipCount.textContent = currentVisitsMemStartDate
                    ? allMemberVisitedDates.filter(vDate => vDate >= currentVisitsMemStartDate).length
                    : allMemberVisitedDates.length;
                
                renderCalendar(currentCalendarDate.getFullYear(), currentCalendarDate.getMonth(), allMemberVisitedDates);
                
                allOtherVisitsContainer.innerHTML = '';
                if (allMemberVisitedDates.length > 0) {
                    allMemberVisitedDates.sort((a,b) => b - a).forEach((visitDate, index) => {
                        allOtherVisitsContainer.innerHTML += `<p><strong>Visit ${allMemberVisitedDates.length - index}:</strong> ${formatDate(visitDate)} ${visitDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</p>`;
                    });
                } else {
                    allOtherVisitsContainer.innerHTML = '<p class="text-gray-600 text-center py-4">No visits to display.</p>';
                }
            } catch (error) {
                console.error('Error fetching member visits:', error);
                showMessage(`Failed to load visit history: ${error.message}`, 'error');
            } finally {
                globalLoadingIndicator.classList.add('hidden');
            }
        }

        prevMonthBtn.addEventListener('click', () => {
            currentCalendarDate.setMonth(currentCalendarDate.getMonth() - 1);
            renderCalendar(currentCalendarDate.getFullYear(), currentCalendarDate.getMonth(), allMemberVisitedDates);
        });

        nextMonthBtn.addEventListener('click', () => {
            currentCalendarDate.setMonth(currentCalendarDate.getMonth() + 1);
            renderCalendar(currentCalendarDate.getFullYear(), currentCalendarDate.getMonth(), allMemberVisitedDates);
        });

        memberVisitsCloseBtn.addEventListener('click', () => showView('familyDetailsView'));

        // --- Initial Load ---
		function startApp() {
		  fetchAllData().then(() => showView('homeView'));
		}

		if (window.apiFetch) {
		  // Auth/Amplify already inited
		  startApp();
		} else {
		  // Wait until index.html announces Auth is ready
		  window.addEventListener('auth-ready', startApp, { once: true });
		}


        // Expose functions to global scope for onclick attributes
        window.editIndividualMember = editIndividualMember;
        window.showAddVisitView = showAddVisitView;
        window.showMemberVisits = showMemberVisits;
        window.checkInFamily = checkInFamily;
        window.deleteSecondaryMember = deleteSecondaryMember;
