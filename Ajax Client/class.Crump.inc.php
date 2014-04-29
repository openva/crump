<?php

/**
 * Crump
 *
 * A class to interface with the Virginia State Corporation Commission's eFile quasi-Ajax API. Named
 * for Beverly T. Crump, the first-ever commissioner of the SCC, from 1903–1907.
 * 
 * PHP version 5
 *
 * @author		Waldo Jaquith <waldo at jaquith.org>
 * @copyright	2013 Waldo Jaquith
 * @license		MIT
 * @version		0.1
 * @link		http://www.github.com/openva/crump
 * @since		0.1
 *
 */
class Crump
{
	
	/**
	 * Get a list of all registered entities that contain a given string within their name. By
	 * default, lists the first 25.
	 *
	 * @returns True or false. If true, $this->results contains the list of search results.
	 */
	function search()
	{
		
		if (!isset($this->name))
		{
			return FALSE;
		}
		
		if (!isset($this->start))
		{
			$this->start = 0;
		}
		
		if (!isset($this->num))
		{
			$this->num = 25;
		}
		
		$url = 'https://sccefile.scc.virginia.gov/Find/AjaxBusiness?searchTerm=' . $this->name
			. '&searchPattern=C&sEcho=1&iDisplayStart=' . $this->start . '&iDisplayLength=' . $this->num;
		
		$ch = curl_init();
		curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, TRUE);
		curl_setopt($ch, CURLOPT_URL, $url);
		curl_setopt($ch, CURLOPT_RETURNTRANSFER, TRUE);
		$allowed_protocols = CURLPROTO_HTTP | CURLPROTO_HTTPS;
		curl_setopt($ch, CURLOPT_PROTOCOLS, $allowed_protocols);
		curl_setopt($ch, CURLOPT_REDIR_PROTOCOLS, $allowed_protocols & ~(CURLPROTO_FILE | CURLPROTO_SCP));
		$this->json = curl_exec($ch);
		curl_close($ch);
		
		if ($this->json === FALSE)
		{
			return FALSE;
		}
		
		/*
		 * Turn the JSON into a PHP object.
		 */
		$this->results = json_decode($this->json);
		
		/*
		 * Remove records we don't need.
		 */
		unset($this->results->sEcho);
		unset($this->results->iTotalDisplayRecords);
		
		/*
		 * Rename "iTotalRecords" to "count."
		 */
		$this->results->count = $this->results->iTotalRecords;
		unset($this->results->iTotalRecords);
		
		/*
		 * Rename "aaData" to "results," and convert it from an array into an object.
		 */
		$this->results->list = (object) $this->results->aaData;
		unset($this->results->aaData);
		
		/*
		 * Iterate through each result and convert it into a keyed object.
		 */
		foreach ($this->results->list as &$result)
		{
		
			$new = new stdClass();
			$new->number = strip_tags($result[1]);
			$new->name = strip_tags($result[2]);
			$new->type = $result[3];
			$new->status = $result[4];
			$result = $new;
			
		}
		
		return TRUE;


	}
	
	/**
	 * See whether a name is already registered.
	 */
	function unique()
	{
	
		if (!isset($this->name))
		{
			return FALSE;
		}
		
		$url = 'https://sccefile.scc.virginia.gov/NameAvailability/GetNameCheckResult?ProposedName='
			. $this->name;

		$ch = curl_init();
		curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, TRUE);
		curl_setopt($ch, CURLOPT_URL, $url);
		curl_setopt($ch, CURLOPT_RETURNTRANSFER, TRUE);
		$allowed_protocols = CURLPROTO_HTTP | CURLPROTO_HTTPS;
		curl_setopt($ch, CURLOPT_PROTOCOLS, $allowed_protocols);
		curl_setopt($ch, CURLOPT_REDIR_PROTOCOLS, $allowed_protocols & ~(CURLPROTO_FILE | CURLPROTO_SCP));
		$this->response = curl_exec($ch);
		curl_close($ch);
		
		if ($this->response === FALSE)
		{
			return FALSE;
		}
		
		if (strstr($this->response, 'Yes, this name is distinguishable') !== FALSE)
		{
			return TRUE;
		}
		elseif (strstr($this->response, 'Name is not distinguishable') !== FALSE)
		{
			return FALSE;
		}
		else
		{
			return FALSE;
		}
		
	}
	
}